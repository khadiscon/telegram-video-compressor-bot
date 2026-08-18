import json
import tempfile
import unittest
from pathlib import Path

from compressor.engine import (
    DEFAULT_PRESET,
    PRESETS,
    build_ffmpeg_command,
    build_vf,
    format_duration,
    human_size,
    parse_ffmpeg_probe,
    parse_frame_rate,
    parse_progress_line,
    progress_bar,
    target_video_bitrate_k,
)


class HumanFormatTests(unittest.TestCase):
    def test_human_size(self) -> None:
        self.assertEqual(human_size(512), "512.0 B")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")

    def test_duration(self) -> None:
        self.assertEqual(format_duration(75), "1:15")
        self.assertEqual(format_duration(3661), "1:01:01")

    def test_frame_rate(self) -> None:
        self.assertAlmostEqual(parse_frame_rate("30000/1001"), 29.97, places=2)
        self.assertEqual(parse_frame_rate("30/1"), 30.0)
        self.assertEqual(parse_frame_rate("0/0"), 0.0)
        self.assertEqual(parse_frame_rate("nope"), 0.0)
        self.assertEqual(parse_frame_rate(None), 0.0)


class ProbeParseTests(unittest.TestCase):
    SAMPLE = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Duration: 00:01:05.12, start: 0.000000, bitrate: 2500 kb/s
  Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 1920x1080, 30 fps, 30 tbr
    rotate          : 90
  Stream #0:1(und): Audio: aac (LC), 48000 Hz, stereo
"""

    def test_parse_probe(self) -> None:
        probe = parse_ffmpeg_probe(self.SAMPLE, file_size=1234)
        self.assertAlmostEqual(probe.duration, 65.12, places=2)
        self.assertEqual(probe.width, 1920)
        self.assertEqual(probe.height, 1080)
        self.assertEqual(probe.codec, "h264")
        self.assertTrue(probe.has_audio)
        self.assertEqual(probe.rotation, 90)
        self.assertEqual(probe.display_width, 1080)
        self.assertEqual(probe.display_height, 1920)
        self.assertEqual(probe.size, 1234)


class ProgressTests(unittest.TestCase):
    def test_out_time_ms(self) -> None:
        frac = parse_progress_line("out_time_ms=5000000", 10.0)
        self.assertIsNotNone(frac)
        self.assertAlmostEqual(frac or 0, 0.5, places=2)

    def test_out_time(self) -> None:
        frac = parse_progress_line("out_time=00:00:02.500000", 10.0)
        self.assertAlmostEqual(frac or 0, 0.25, places=2)

    def test_end(self) -> None:
        self.assertEqual(parse_progress_line("progress=end", 10.0), 1.0)

    def test_bar(self) -> None:
        bar = progress_bar(0.5, width=10)
        self.assertIn("50%", bar)
        self.assertEqual(bar.count("█"), 5)


class CommandTests(unittest.TestCase):
    def test_scale_never_upscales(self) -> None:
        vf = build_vf(PRESETS["strong"])
        self.assertIn("if(gt(ih,720)", vf)
        self.assertIn("trunc(iw/2)*2", vf)

    def test_crf_command(self) -> None:
        cmd = build_ffmpeg_command(
            Path("in.mp4"), Path("out.mp4"), PRESETS["medium"], duration=10
        )
        self.assertIn("-crf", cmd)
        self.assertIn("23", cmd)
        self.assertIn("+faststart", cmd)
        self.assertIn("libx264", cmd)

    def test_target_bitrate_command(self) -> None:
        cmd = build_ffmpeg_command(
            Path("in.mp4"), Path("out.mp4"), PRESETS["tg8"], duration=60
        )
        self.assertIn("-b:v", cmd)
        self.assertNotIn("-crf", cmd)

    def test_bitrate_math(self) -> None:
        br = target_video_bitrate_k(60, 8, "80k")
        # 8MB over 60s minus audio should be a few hundred kbps, not tiny/huge.
        self.assertGreater(br, 200)
        self.assertLess(br, 2000)

    def test_default_preset_exists(self) -> None:
        self.assertIn(DEFAULT_PRESET, PRESETS)


if __name__ == "__main__":
    unittest.main()
