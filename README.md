# Video Cut Extractor

A small Python CLI for turning a source video into an edited template of named cuts. It can export explicit ranges or detect hard cuts within a requested range. By default it creates a timing manifest without rendering video clips; use `--render-clips` when you need exported media.

## Features

- Accepts one source video and any number of time ranges
- Detects candidate hard cuts automatically with FFmpeg scene scores
- Supports timestamp strings such as `00:15`, `01:02:03`, and `00:00:05-00:00:12`
- Exports clips with a human-friendly label or a generated sequential name
- Writes a reusable `manifest.json` for the template
- Preserves audio in rendered cuts by default
- Supports manifest-only runs to avoid unnecessary video rendering

## Requirements

- Python 3.10+
- FFmpeg installed and available in `PATH`

## Usage

```bash
python video_cut_extractor.py "source.mp4" \
  --cut "00:00:00-00:00:04@intro" \
  --cut "00:00:20-00:00:32@recovery" \
  --output-dir "recovery-template"
```

The command creates a folder like this:

```text
recovery-template/
├── clips/
│   ├── intro.mp4
│   └── recovery.mp4
├── manifest.json
└── notes.txt
```

You can omit audio for a silent cut test:

```bash
python video_cut_extractor.py "source.mp4" --cut "00:00:00-00:00:04" --no-audio
```

To detect every candidate cut in a range:

```bash
python video_cut_extractor.py "source.mp4" \\
  --range "02:28-02:59" \\
  --detect-cuts \\
  --threshold 0.30 \\
  --min-shot-length 0.08 \\
  --output-dir "world-is-yours-template"
```

This default workflow creates `analysis/manifest.json`, `analysis/notes.txt`, and a self-contained
`analysis/manifest.html` timeline viewer. Open `analysis/manifest.html` in a browser to inspect
the detected cut rhythm. To also
render one audio-preserving MP4 per detected shot, add:

```bash
--render-clips
```

To create a CMX3600 EDL for import into DaVinci Resolve:

```bash
python video_cut_extractor.py "source.mp4" \\
  --range "02:28-02:59" \\
  --detect-cuts \\
  --export-edl \\
  --fps 30 \\
  --output-dir "resolve-template"
```

This creates `analysis/timeline.edl`. In Resolve, use `File > Import Timeline > Pre-conformed EDL`.
The EDL carries video timing and source references; keep the original audio on a
separate track because CMX3600 EDL support for audio varies by editor.

For a template that does not reference the original video, generate slot media:

```bash
python video_cut_extractor.py "source.mp4" \\
  --range "02:28-02:59" \\
  --detect-cuts \\
  --export-edl \\
  --placeholders \\
  --fps 30 \\
  --output-dir "resolve-template"
```

This creates `template/placeholders/shot-001.mp4`, `template/placeholders/shot-002.mp4`, and so
on. The EDL references those neutral clips rather than the reference video.
Import the placeholder media and `timeline.edl` into Resolve, then use
`Replace Selected Clip` or replace the placeholder media in the Media Pool with
your recovery footage. Keep the placeholder dimensions and frame rate consistent
with the target timeline. Placeholder slots use a repeating six-color palette,
so neighboring cuts are easy to see in Kdenlive while you are replacing media.

For a portrait template, select the orientation:

```bash
python video_cut_extractor.py "source.mp4" \\
  --range "02:28-02:59" \\
  --detect-cuts \\
  --export-edl \\
  --placeholders \\
  --orientation portrait \\
  --output-dir "resolve-portrait-template"
```

Portrait defaults to `1080x1920`; landscape defaults to `1920x1080`. You can
override both dimensions with `--placeholder-width` and `--placeholder-height`.

To render one final portrait template video containing every detected cut and
the reference audio, add `--render-template`:

```bash
python video_cut_extractor.py "source.mp4" \\
  --range "02:28-02:59" \\
  --detect-cuts \\
  --placeholders \\
  --render-template \\
  --orientation portrait \\
  --output-dir "kdenlive-portrait-template"
```

This creates `template/template.mp4` for immediate preview/import into Kdenlive, along
with the individual `template/placeholders/` clips and `analysis/timeline.edl` when
`--export-edl` is also supplied.

Lower `--threshold` finds more changes. Increase `--min-shot-length` to group
very short flashes or scratch-driven edits. Automatic detection is a candidate
map: review the generated timings before treating it as a final template.

## Timestamp formats

- `10` -> 10 seconds
- `01:30` -> 1 minute 30 seconds
- `00:05:20` -> 5 minutes 20 seconds
- `00:00:00-00:00:05` -> segment from start to end
- `00:00:00-00:00:05@intro` -> segment with a label

## Notes

This tool is designed for creating an editable cut package, not for final color grading or compositing. It is intentionally lightweight and works well with a source video and an external timeline editor such as DaVinci Resolve. The generated `manifest.json` is written before optional clip rendering so a long run can be inspected without waiting for media exports.

## Compare a generated sequence

Use `compare_video.py` to create a throwaway synchronized comparison. The
reference is shown on the left, the generated template on the right, and a
white divider marks the boundary. Audio comes from the reference video.

```powershell
python compare_video.py `
  --reference "Nas - The World Is Yours (Official HD Video) - Nas (1080p).mp4" `
  --generated "output\world-is-yours-0228-0259\template\template.mp4" `
  --start "02:28" `
  --end "02:59" `
  --project-dir "output\world-is-yours-0228-0259"
```

The default output uses two `960x1080` panels. The original landscape video is
letterboxed on the left and the portrait template is letterboxed on the right,
so both timelines remain visible and synchronized.

## Output structure

Each run uses the output directory as a project bundle:

```text
project-output/
├── analysis/
│   ├── manifest.json
│   ├── manifest.html
│   ├── notes.txt
│   └── timeline.edl
├── template/
│   ├── template.mp4
│   ├── template-audio.m4a
│   └── placeholders/
└── comparison/
  └── reference-vs-template.mp4
```
