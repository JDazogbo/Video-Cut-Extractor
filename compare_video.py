#!/usr/bin/env python3
"""Render a side-by-side comparison between a reference and generated video."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable

    roots = []
    for name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "USERPROFILE"):
        value = os.environ.get(name)
        if value:
            roots.append(Path(value))
    for root in roots:
        for candidate_root in (
            root / "Microsoft" / "WinGet" / "Packages",
            root / "ffmpeg" / "bin",
            root / "FFmpeg" / "bin",
            root,
        ):
            if not candidate_root.exists():
                continue
            for match in candidate_root.rglob("ffmpeg.exe"):
                return str(match)

    raise RuntimeError("FFmpeg was not found. Install it or add it to PATH.")


def parse_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3 or any(not part for part in parts):
        raise ValueError(f"Invalid timestamp: {value!r}")
    numbers = [float(part) for part in parts]
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def render_comparison(
    reference: Path,
    generated: Path,
    output: Path,
    start: float,
    duration: float,
    ffmpeg: str,
    panel_width: int,
    panel_height: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        f"[0:v]setpts=PTS-STARTPTS,scale={panel_width}:{panel_height}:"
        "force_original_aspect_ratio=decrease,pad="
        f"{panel_width}:{panel_height}:(ow-iw)/2:(oh-ih)/2:color=black[left];"
        f"[1:v]setpts=PTS-STARTPTS,scale={panel_width}:{panel_height}:"
        "force_original_aspect_ratio=decrease,pad="
        f"{panel_width}:{panel_height}:(ow-iw)/2:(oh-ih)/2:color=black[right];"
        "[left][right]hstack=inputs=2,"
        f"drawbox=x={panel_width - 3}:y=0:w=6:h={panel_height}:"
        "color=white:t=fill[outv]"
    )
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(reference),
        "-t",
        str(duration),
        "-i",
        str(generated),
        "-filter_complex",
        filter_graph,
        "-map",
        "[outv]",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(command, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a synchronized reference/generated side-by-side comparison."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--start", default="00:00")
    parser.add_argument("--end", default=None)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--output", type=Path, default=Path("comparison.mp4"))
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Write comparison/reference-vs-template.mp4 under this project directory.",
    )
    parser.add_argument("--panel-width", type=int, default=960)
    parser.add_argument("--panel-height", type=int, default=1080)
    parser.add_argument("--ffmpeg", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.reference.exists():
        parser.error(f"Reference not found: {args.reference}")
    if not args.generated.exists():
        parser.error(f"Generated video not found: {args.generated}")
    if args.panel_width <= 0 or args.panel_height <= 0:
        parser.error("Panel dimensions must be greater than zero.")
    try:
        if args.project_dir is not None:
            args.output = args.project_dir / "comparison" / "reference-vs-template.mp4"
        start = parse_seconds(args.start)
        if start < 0:
            raise ValueError("Start time cannot be negative.")
        if args.duration is not None and args.duration <= 0:
            raise ValueError("Duration must be greater than zero.")
        if args.end is not None:
            duration = parse_seconds(args.end) - start
        elif args.duration is not None:
            duration = args.duration
        else:
            raise ValueError("Provide either --end or --duration.")
        if duration <= 0:
            raise ValueError("End time must be after start time.")
        render_comparison(
            args.reference,
            args.generated,
            args.output,
            start,
            duration,
            args.ffmpeg or resolve_ffmpeg(),
            args.panel_width,
            args.panel_height,
        )
        print(f"Created comparison video: {args.output}")
        return 0
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
