"""Optional live encode test. Skips if ffmpeg is missing."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from compressor.engine import PRESETS, compress_video, probe_video


def _make_clip(path: Path) -> None:
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1.5:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class LiveEncodeTests(unittest.TestCase):
    def test_medium_encode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.mp4"
            dst = Path(tmp) / "out.mp4"
            _make_clip(src)
            probe = probe_video(src)
            self.assertGreater(probe.duration, 1.0)
            self.assertEqual(probe.width, 320)
            result = asyncio.run(
                compress_video(
                    src,
                    dst,
                    PRESETS["medium"],
                    duration=probe.duration,
                    timeout=60,
                )
            )
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.output)
            self.assertTrue(dst.exists())
            self.assertGreater(dst.stat().st_size, 0)
            out = probe_video(dst)
            self.assertGreater(out.duration, 1.0)
            self.assertLessEqual(out.height, 240)


if __name__ == "__main__":
    unittest.main()
