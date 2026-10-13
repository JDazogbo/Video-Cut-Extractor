import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from video_cut_extractor import (
    Segment,
    detect_cut_points,
    extract_segment,
    parse_segment_spec,
    parse_timestamp,
    write_edl,
)


class VideoCutExtractorTests(unittest.TestCase):
    def test_parse_timestamp_variants(self):
        self.assertEqual(parse_timestamp("10"), 10.0)
        self.assertEqual(parse_timestamp("01:30"), 90.0)
        self.assertEqual(parse_timestamp("00:05:20"), 320.0)

    def test_parse_segment_spec_with_label(self):
        start, end, label = parse_segment_spec("00:00:10-00:00:18@recovery", 1)
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 18.0)
        self.assertEqual(label, "recovery")

    def test_parse_segment_spec_without_label(self):
        start, end, label = parse_segment_spec("00:00:20-00:00:40", 2)
        self.assertEqual(start, 20.0)
        self.assertEqual(end, 40.0)
        self.assertEqual(label, "clip-002")

    @patch("video_cut_extractor.subprocess.run")
    def test_detect_cut_points_uses_scene_timestamps(self, run):
        run.return_value.stderr = "pts_time:0.50\\npts_time:0.55\\npts_time:1.25\\n"
        points = detect_cut_points(
            source_video="source.mp4",
            start=10.0,
            end=12.0,
            threshold=0.3,
            minimum_shot_length=0.1,
            ffmpeg_executable="ffmpeg",
        )
        self.assertEqual(points, [10.0, 10.5, 11.25, 12.0])
        run.assert_called_once()

    @patch("video_cut_extractor.subprocess.run")
    def test_extract_segment_creates_missing_output_directory(self, run):
        with TemporaryDirectory() as temporary_directory:
            output_file = Path(temporary_directory) / "clips" / "shot-035.mp4"
            extract_segment(
                Path("source.mp4"),
                output_file,
                10.0,
                11.0,
                include_audio=True,
                ffmpeg_executable="ffmpeg",
            )
            self.assertTrue(output_file.parent.is_dir())
            run.assert_called_once()

    @patch("video_cut_extractor.subprocess.run")
    def test_create_placeholder_uses_requested_color(self, run):
        from video_cut_extractor import create_placeholder

        with TemporaryDirectory() as temporary_directory:
            output_file = Path(temporary_directory) / "placeholders" / "shot-001.mp4"
            create_placeholder(output_file, 1.0, 180, 320, 30, "6b3f69", "ffmpeg")
            command = run.call_args.args[0]
            self.assertIn("color=c=0x6b3f69:s=180x320:r=30", command)

    def test_write_edl_uses_manifest_timing(self):
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            write_edl(
                output_dir,
                Path("reference.mp4"),
                [Segment("shot-001", 148.0, 148.5, "clips/shot-001.mp4")],
                frames_per_second=30,
            )
            edl = (output_dir / "timeline.edl").read_text(encoding="ascii")
            self.assertIn("001  AX       V     C        00:02:28:00 00:02:28:15 00:00:00:00 00:00:00:15", edl)
            self.assertIn("* SLOT: shot-001", edl)

    def test_write_edl_uses_local_placeholder_timecodes(self):
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            write_edl(
                output_dir,
                Path("reference.mp4"),
                [Segment("shot-001", 148.0, 148.5, "placeholders/shot-001.mp4")],
                frames_per_second=30,
                use_placeholders=True,
            )
            edl = (output_dir / "timeline.edl").read_text(encoding="ascii")
            self.assertIn("00:00:00:00 00:00:00:15 00:00:00:00 00:00:00:15", edl)
            self.assertIn("* FROM CLIP NAME: shot-001.mp4", edl)
            self.assertNotIn("reference.mp4", edl)


if __name__ == "__main__":
    unittest.main()
