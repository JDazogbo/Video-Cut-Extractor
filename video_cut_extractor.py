#!/usr/bin/env python3
"""Extract named cuts from a source video into a reusable editing template."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

TIMESTAMP_PATTERN = re.compile(r"^[0-9]+(?::[0-9]+){0,2}(?:\.[0-9]+)?$")
PLACEHOLDER_COLORS = ("27363b", "6b3f69", "8a5a2b", "285943", "713b3b", "355c7d")


@dataclass
class Segment:
    label: str
    start: float
    end: float
    output_path: str


def detect_cut_points(
    source_video: Path,
    start: float,
    end: float,
    threshold: float,
    minimum_shot_length: float,
    ffmpeg_executable: str,
) -> List[float]:
    """Return source-relative candidate hard-cut times from FFmpeg scene scores."""
    duration = end - start
    filter_expression = f"select=gt(scene\\,{threshold}),showinfo"
    command = [
        ffmpeg_executable,
        "-hide_banner",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(source_video),
        "-vf",
        filter_expression,
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    candidate_pattern = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
    relative_points = [float(match.group(1)) for match in candidate_pattern.finditer(result.stderr)]

    points = [start]
    last_point = start
    for relative_point in relative_points:
        point = min(end, start + relative_point)
        if point - last_point >= minimum_shot_length and point < end:
            points.append(point)
            last_point = point
    if end - points[-1] < minimum_shot_length and len(points) > 1:
        points.pop()
    points.append(end)
    return points


def segments_from_boundaries(boundaries: Iterable[float]) -> List[Segment]:
    values = list(boundaries)
    return [
        Segment(
            label=f"shot-{index:03d}",
            start=start,
            end=end,
            output_path=f"clips/shot-{index:03d}.mp4",
        )
        for index, (start, end) in enumerate(zip(values, values[1:]), start=1)
    ]


def slugify(value: str) -> str:
    value = value.strip().lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "clip"


def parse_timestamp(raw_value: str) -> float:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("Timestamp cannot be empty.")

    if "," in value:
        value = value.replace(",", ".")

    if not TIMESTAMP_PATTERN.match(value):
        raise ValueError(f"Invalid timestamp: {raw_value!r}")

    parts = [float(part) for part in value.split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) >= 3:
        hours = parts[0]
        minutes = parts[1]
        seconds = parts[2]
        return hours * 3600 + minutes * 60 + seconds

    raise ValueError(f"Unsupported timestamp format: {raw_value!r}")


def parse_segment_spec(raw_segment: str, index: int) -> tuple[float, float, str]:
    candidate = (raw_segment or "").strip()
    if not candidate:
        raise ValueError("A cut cannot be empty.")

    label = None
    for token in ("@", "|"):
        if token in candidate:
            candidate, label = candidate.split(token, 1)
            break

    if "-" in candidate or "–" in candidate:
        separator = "-" if "-" in candidate else "–"
        start_text, end_text = candidate.split(separator, 1)
        start = parse_timestamp(start_text)
        end = parse_timestamp(end_text)
    else:
        start = parse_timestamp(candidate)
        end = start + 1.0

    if end <= start:
        raise ValueError(f"Cut '{raw_segment}' ends before or at its start time.")

    if label:
        safe_label = slugify(label)
    else:
        safe_label = f"clip-{index:03d}"

    return start, end, safe_label


def build_output_structure(output_dir: Path, clip_count: int, render_clips: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (output_dir / "template").mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison").mkdir(parents=True, exist_ok=True)
    if render_clips:
        (output_dir / "template" / "clips").mkdir(parents=True, exist_ok=True)
    if clip_count == 0:
        (output_dir / "notes.txt").write_text("No cuts generated.\n", encoding="utf-8")


def resolve_ffmpeg_executable() -> str:
    direct = shutil.which("ffmpeg")
    if direct:
        return direct

    candidate_roots = []
    for env_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "USERPROFILE"):
        value = os.environ.get(env_name)
        if value:
            candidate_roots.append(Path(value))

    for root in candidate_roots:
        for candidate in [
            root / "Microsoft" / "WinGet" / "Packages",
            root / "ffmpeg" / "bin",
            root / "FFmpeg" / "bin",
            root,
        ]:
            if not candidate.exists():
                continue
            for match in candidate.rglob("ffmpeg.exe"):
                return str(match)

    raise RuntimeError("FFmpeg could not be found on PATH or in the common Windows install locations. Install FFmpeg and try again.")


def ensure_ffmpeg() -> str:
    return resolve_ffmpeg_executable()


def format_duration(total_seconds: float) -> str:
    seconds = int(total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def extract_segment(
    source_video: Path,
    output_file: Path,
    start: float,
    end: float,
    include_audio: bool,
    ffmpeg_executable: str,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, end - start)
    command = [
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(source_video),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
    ]

    if include_audio:
        command.extend(["-c:a", "aac", "-movflags", "+faststart"])
    else:
        command.append("-an")

    command.append(str(output_file))

    subprocess.run(command, check=True)


def create_placeholder(
    output_file: Path,
    duration: float,
    width: int,
    height: int,
    frames_per_second: float,
    color: str,
    ffmpeg_executable: str,
) -> None:
    """Create a colored slot clip for editor timeline replacement."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x{color}:s={width}x{height}:r={frames_per_second}",
        "-t",
        str(max(0.1, duration)),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_file),
    ]
    subprocess.run(command, check=True)


def render_template_video(
    output_file: Path,
    placeholder_files: Iterable[Path],
    source_video: Path,
    start: float,
    duration: float,
    ffmpeg_executable: str,
) -> None:
    """Concatenate slot media and mux the exact selected source audio range."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output_file.with_suffix(".concat.txt")
    placeholder_list = list(placeholder_files)
    concat_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for path in placeholder_list) + "\n",
        encoding="utf-8",
    )
    video_file = output_file.with_name(output_file.stem + "-video.mp4")
    concat_command = [
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(video_file),
    ]
    subprocess.run(concat_command, check=True)

    audio_file = output_file.with_name(output_file.stem + "-audio.m4a")
    audio_command = [
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(source_video),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-af",
        "aresample=async=1:first_pts=0",
        str(audio_file),
    ]
    subprocess.run(audio_command, check=True)

    mux_command = [
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_file),
        "-i",
        str(audio_file),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_file),
    ]
    subprocess.run(mux_command, check=True)
    concat_file.unlink(missing_ok=True)
    video_file.unlink(missing_ok=True)


def generate_manifest(
    output_dir: Path,
    source_video: Path,
    segments: Iterable[Segment],
    audio_preserved: bool = True,
    clips_rendered: bool = False,
    orientation: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> None:
    segment_list = list(segments)
    payload = {
        "source_video": str(source_video),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audio_preserved": audio_preserved,
        "clips_rendered": clips_rendered,
        "orientation": orientation,
        "width": width,
        "height": height,
        "segments": [
            {
                "label": segment.label,
                "start": segment.start,
                "end": segment.end,
                "duration": segment.end - segment.start,
                "output_path": segment.output_path,
            }
            for segment in segment_list
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_notes(output_dir: Path, segments: Iterable[Segment], clips_rendered: bool) -> None:
    lines = ["Video Cut Template", "=================", ""]
    if not clips_rendered:
        lines.append("Manifest-only run: no video clips were rendered.")
        lines.append("Use --render-clips to export each shot as an MP4.")
        lines.append("")
    for segment in segments:
        lines.append(f"- {segment.label}: {format_duration(segment.start)} to {format_duration(segment.end)} -> clips/{Path(segment.output_path).name}")
    lines.append("")
    (output_dir / "notes.txt").write_text("\n".join(lines), encoding="utf-8")


def write_manifest_html(output_dir: Path, segments: Iterable[Segment]) -> None:
    segment_list = list(segments)
    if not segment_list:
        body = "<p>No segments detected.</p>"
    else:
        start_time = segment_list[0].start
        end_time = segment_list[-1].end
        total_duration = max(0.001, end_time - start_time)
        rows = []
        for segment in segment_list:
            left = ((segment.start - start_time) / total_duration) * 100
            width = ((segment.end - segment.start) / total_duration) * 100
            rows.append(
                "<article class=\"shot\">"
                f"<div class=\"shot-label\"><strong>{segment.label}</strong> "
                f"{format_duration(segment.start)} - {format_duration(segment.end)} "
                f"({segment.end - segment.start:.3f}s)</div>"
                "<div class=\"track\"><div class=\"bar\" "
                f"style=\"left:{left:.4f}%;width:{width:.4f}%\"></div></div>"
                "</article>"
            )
        body = "".join(rows)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video Cut Manifest</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; background: #f4f1ea; color: #202326; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px; }}
h1 {{ margin-bottom: 4px; }}
.subtitle {{ color: #5c6268; margin-top: 0; }}
.shot {{ display: grid; grid-template-columns: 280px 1fr; gap: 16px; align-items: center; margin: 10px 0; }}
.shot-label {{ font-size: 13px; font-variant-numeric: tabular-nums; }}
.shot-label strong {{ display: inline-block; width: 72px; color: #b0442f; }}
.track {{ position: relative; height: 24px; background: #dedbd3; border-radius: 4px; overflow: hidden; }}
.bar {{ position: absolute; top: 0; bottom: 0; min-width: 3px; background: #2f6f68; border-right: 2px solid #173f3c; }}
@media (max-width: 700px) {{ .shot {{ grid-template-columns: 1fr; gap: 5px; }} }}
</style>
</head>
<body>
<h1>Detected Cut Timeline</h1>
<p class="subtitle">{len(segment_list)} segments from {format_duration(segment_list[0].start) if segment_list else "-"} to {format_duration(segment_list[-1].end) if segment_list else "-"}</p>
{body}
</body>
</html>
"""
    (output_dir / "manifest.html").write_text(html, encoding="utf-8")


def timecode_from_seconds(seconds: float, frames_per_second: float) -> str:
    total_frames = max(0, round(seconds * frames_per_second))
    frames = total_frames % round(frames_per_second)
    total_seconds = total_frames // round(frames_per_second)
    whole_seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}:{frames:02d}"


def write_edl(
    output_dir: Path,
    source_video: Path,
    segments: Iterable[Segment],
    frames_per_second: float,
    use_placeholders: bool = False,
) -> None:
    """Write a CMX3600 EDL using source media or generated slot placeholders."""
    segment_list = list(segments)
    if frames_per_second <= 0:
        raise ValueError("--fps must be greater than zero.")

    timeline_start = segment_list[0].start if segment_list else 0.0
    lines = [
        "TITLE: Video Cut Extractor",
        f"FCM: NON-DROP FRAME",
        "",
    ]
    for index, segment in enumerate(segment_list, start=1):
        record_start = segment.start - timeline_start
        record_end = segment.end - timeline_start
        source_start = 0.0 if use_placeholders else segment.start
        source_end = segment.end - segment.start if use_placeholders else segment.end
        lines.append(
            f"{index:03d}  AX       V     C        "
            f"{timecode_from_seconds(source_start, frames_per_second)} "
            f"{timecode_from_seconds(source_end, frames_per_second)} "
            f"{timecode_from_seconds(record_start, frames_per_second)} "
            f"{timecode_from_seconds(record_end, frames_per_second)}"
        )
        if use_placeholders:
            clip_name = Path(segment.output_path).name
        else:
            clip_name = source_video.name
        lines.append(f"* FROM CLIP NAME: {clip_name}")
        lines.append(f"* REEL: {Path(clip_name).stem[:8].upper()}")
        lines.append(f"* SLOT: {segment.label}")
    (output_dir / "timeline.edl").write_text("\n".join(lines) + "\n", encoding="ascii")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract time-based video cuts into a reusable template.")
    parser.add_argument("video", type=Path, help="Path to the source video file.")
    parser.add_argument(
        "--cut",
        dest="cuts",
        action="append",
        default=[],
        help="A cut definition like '00:00:00-00:00:05@intro' or '00:12-00:20'.",
    )
    parser.add_argument(
        "--range",
        dest="time_range",
        help="Range to analyze, for example '02:28-02:59'. Use with --detect-cuts.",
    )
    parser.add_argument(
        "--detect-cuts",
        action="store_true",
        help="Detect hard cuts automatically inside --range using FFmpeg scene scores.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="FFmpeg scene-change threshold from 0 to 1. Lower values detect more cuts.",
    )
    parser.add_argument(
        "--min-shot-length",
        type=float,
        default=0.08,
        help="Ignore detected cuts that are closer together than this many seconds.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("video-template"),
        help="Where to place the exported template files.",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Skip audio in each extracted clip. Default is to include it.",
    )
    parser.add_argument(
        "--render-clips",
        action="store_true",
        help="Render one MP4 per segment. By default, only the manifest and notes are generated.",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Do not create the self-contained manifest.html timeline viewer.",
    )
    parser.add_argument(
        "--export-edl",
        action="store_true",
        help="Write a CMX3600 timeline.edl from the detected segments.",
    )
    parser.add_argument(
        "--placeholders",
        action="store_true",
        help="Create replaceable placeholder MP4s and make the EDL reference them.",
    )
    parser.add_argument(
        "--render-template",
        action="store_true",
        help="Render one final template.mp4 from the generated placeholders and reference audio.",
    )
    parser.add_argument(
        "--placeholder-width",
        type=int,
        default=None,
        help="Width of generated placeholder media. Defaults from --orientation.",
    )
    parser.add_argument(
        "--placeholder-height",
        type=int,
        default=None,
        help="Height of generated placeholder media. Defaults from --orientation.",
    )
    parser.add_argument(
        "--orientation",
        choices=("landscape", "portrait"),
        default="landscape",
        help="Placeholder format. Landscape defaults to 1920x1080; portrait to 1080x1920.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Frame rate used when converting manifest seconds to EDL timecodes.",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.video.exists():
        parser.error(f"File not found: {args.video}")
    if args.detect_cuts and not args.time_range:
        parser.error("--detect-cuts requires --range, for example --range 02:28-02:59.")
    if args.cuts and args.detect_cuts:
        parser.error("Use either --cut or --detect-cuts, not both.")
    if not args.cuts and not args.detect_cuts:
        parser.error("Provide at least one --cut value or use --detect-cuts with --range.")

    try:
        ffmpeg_executable = ensure_ffmpeg()
        output_dir = args.output_dir
        analysis_dir = output_dir / "analysis"
        template_dir = output_dir / "template"
        if args.render_template:
            args.placeholders = True
        if (args.placeholder_width is None) != (args.placeholder_height is None):
            raise ValueError("Provide both --placeholder-width and --placeholder-height, or neither.")
        if args.placeholder_width is None:
            if args.orientation == "portrait":
                placeholder_width, placeholder_height = 1080, 1920
            else:
                placeholder_width, placeholder_height = 1920, 1080
        else:
            placeholder_width, placeholder_height = args.placeholder_width, args.placeholder_height
        if placeholder_width <= 0 or placeholder_height <= 0:
            raise ValueError("Placeholder dimensions must be greater than zero.")
        segments: List[Segment] = []
        if args.detect_cuts:
            range_start, range_end, _ = parse_segment_spec(args.time_range, 1)
            if not 0 <= args.threshold <= 1:
                raise ValueError("--threshold must be between 0 and 1.")
            if args.min_shot_length <= 0:
                raise ValueError("--min-shot-length must be greater than zero.")
            boundaries = detect_cut_points(
                args.video,
                range_start,
                range_end,
                args.threshold,
                args.min_shot_length,
                ffmpeg_executable,
            )
            segments = segments_from_boundaries(boundaries)
        else:
            for index, raw_segment in enumerate(args.cuts, start=1):
                start, end, label = parse_segment_spec(raw_segment, index)
                segments.append(
                    Segment(
                        label=label,
                        start=start,
                        end=end,
                        output_path=f"template/clips/{label}.mp4",
                    )
                )

        for segment in segments:
            segment.output_path = f"template/clips/{Path(segment.output_path).name}"

        build_output_structure(output_dir, len(segments), args.render_clips)
        generate_manifest(
            analysis_dir,
            args.video,
            segments,
            audio_preserved=args.render_clips and not args.no_audio,
            clips_rendered=args.render_clips,
            orientation=args.orientation,
            width=placeholder_width if args.placeholders else None,
            height=placeholder_height if args.placeholders else None,
        )
        if args.render_clips:
            for segment in segments:
                output_file = output_dir / segment.output_path
                extract_segment(
                    args.video,
                    output_file,
                    segment.start,
                    segment.end,
                    include_audio=not args.no_audio,
                    ffmpeg_executable=ffmpeg_executable,
                )
        if args.placeholders:
            placeholder_files = []
            for index, segment in enumerate(segments):
                placeholder_file = template_dir / "placeholders" / Path(segment.output_path).name
                placeholder_files.append(placeholder_file)
                create_placeholder(
                    placeholder_file,
                    segment.end - segment.start,
                    placeholder_width,
                    placeholder_height,
                    args.fps,
                    PLACEHOLDER_COLORS[index % len(PLACEHOLDER_COLORS)],
                    ffmpeg_executable,
                )
            if args.render_template and segments:
                render_template_video(
                    template_dir / "template.mp4",
                    placeholder_files,
                    args.video,
                    segments[0].start,
                    segments[-1].end - segments[0].start,
                    ffmpeg_executable,
                )

        write_notes(analysis_dir, segments, args.render_clips)
        if not args.no_html:
            write_manifest_html(analysis_dir, segments)
        if args.export_edl:
            if args.placeholders:
                for segment in segments:
                    segment.output_path = f"template/placeholders/{Path(segment.output_path).name}"
                generate_manifest(
                    analysis_dir,
                    args.video,
                    segments,
                    audio_preserved=False,
                    clips_rendered=False,
                    orientation=args.orientation,
                    width=placeholder_width,
                    height=placeholder_height,
                )
            write_edl(analysis_dir, args.video, segments, args.fps, use_placeholders=args.placeholders)

        mode = "clip(s)" if args.render_clips else "manifest segment(s)"
        print(f"Created {len(segments)} {mode} in {output_dir}")
        for segment in segments:
            print(f"- {segment.label}: {segment.start}s -> {segment.end}s")
        return 0
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
