"""FFmpeg compression engine. No Telegram imports — unit-testable on its own."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal

logger = logging.getLogger("compressor.engine")

CodecName = Literal["libx264", "libx265"]
PresetId = Literal["light", "medium", "strong", "ultra", "tg8", "tg2"]

ProgressFn = Callable[[float], Awaitable[None] | None]


@dataclass(frozen=True)
class Preset:
    id: PresetId
    label: str
    blurb: str
    codec: CodecName
    crf: int | None
    target_mb: float | None
    max_height: int
    audio_bitrate: str
    ffmpeg_preset: str
    max_fps: int | None = None


PRESETS: dict[PresetId, Preset] = {
    "light": Preset(
        id="light",
        label="Light",
        blurb="Keeps most detail. Modest size drop.",
        codec="libx264",
        crf=20,
        target_mb=None,
        max_height=1080,
        audio_bitrate="128k",
        ffmpeg_preset="medium",
    ),
    "medium": Preset(
        id="medium",
        label="Medium",
        blurb="Balanced quality and size. Default.",
        codec="libx264",
        crf=23,
        target_mb=None,
        max_height=1080,
        audio_bitrate="96k",
        ffmpeg_preset="medium",
    ),
    "strong": Preset(
        id="strong",
        label="Strong",
        blurb="Aggressive shrink. Still watchable.",
        codec="libx264",
        crf=28,
        target_mb=None,
        max_height=720,
        audio_bitrate="80k",
        ffmpeg_preset="fast",
        max_fps=30,
    ),
    "ultra": Preset(
        id="ultra",
        label="Ultra",
        blurb="Smallest file. Caps at 720p.",
        codec="libx264",
        crf=32,
        target_mb=None,
        max_height=720,
        audio_bitrate="64k",
        ffmpeg_preset="veryfast",
        max_fps=24,
    ),
    "tg8": Preset(
        id="tg8",
        label="8 MB",
        blurb="Fits Telegram's usual send limit.",
        codec="libx264",
        crf=None,
        target_mb=8,
        max_height=720,
        audio_bitrate="80k",
        ffmpeg_preset="fast",
        max_fps=30,
    ),
    "tg2": Preset(
        id="tg2",
        label="2 MB",
        blurb="Tiny share. Expects visible loss.",
        codec="libx264",
        crf=None,
        target_mb=2,
        max_height=480,
        audio_bitrate="48k",
        ffmpeg_preset="veryfast",
        max_fps=24,
    ),
}

DEFAULT_PRESET: PresetId = "medium"


@dataclass
class Probe:
    duration: float = 0.0
    size: int = 0
    width: int = 0
    height: int = 0
    codec: str = "unknown"
    fps: float = 0.0
    has_audio: bool = False
    rotation: int = 0

    @property
    def display_width(self) -> int:
        if abs(self.rotation) in {90, 270}:
            return self.height
        return self.width

    @property
    def display_height(self) -> int:
        if abs(self.rotation) in {90, 270}:
            return self.width
        return self.height


@dataclass
class CompressResult:
    ok: bool
    output: Path | None
    elapsed: float
    original_size: int
    compressed_size: int
    skipped_larger: bool = False
    error: str | None = None

    @property
    def ratio(self) -> float:
        if self.original_size <= 0:
            return 0.0
        return 1.0 - (self.compressed_size / self.original_size)


class JobCancelled(Exception):
    """Raised when the user or supervisor cancels a running encode."""


def human_size(num_bytes: int | float) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def parse_frame_rate(raw: str | None) -> float:
    if not raw:
        return 0.0
    text = str(raw).strip()
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            n = float(num)
            d = float(den)
        except ValueError:
            return 0.0
        if d == 0:
            return 0.0
        return n / d
    try:
        return float(text)
    except ValueError:
        return 0.0


def ffmpeg_available(bin_name: str = "ffmpeg") -> bool:
    return shutil.which(bin_name) is not None


def codec_available(codec: str, bin_name: str = "ffmpeg") -> bool:
    try:
        result = __import__("subprocess").run(
            [bin_name, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, OSError):
        return False
    return codec in (result.stdout or "")


def resolve_preset(preset_id: str) -> Preset:
    if preset_id not in PRESETS:
        raise KeyError(preset_id)
    return PRESETS[preset_id]  # type: ignore[index]


def target_video_bitrate_k(duration: float, target_mb: float, audio_bitrate: str) -> int:
    """Estimate video bitrate (kbps) that should land near target_mb."""
    audio_k = _parse_kbps(audio_bitrate)
    usable = max(0.4, duration)
    total_kbits = target_mb * 1024 * 8
    # Leave ~6% mux/container headroom.
    budget = total_kbits * 0.94
    video_k = (budget / usable) - audio_k
    return max(80, int(video_k))


def _parse_kbps(value: str) -> int:
    text = value.strip().lower()
    if text.endswith("k"):
        text = text[:-1]
    try:
        return max(16, int(float(text)))
    except ValueError:
        return 96


def build_vf(preset: Preset) -> str:
    """Scale down only, even dimensions, optional fps cap."""
    h = max(2, preset.max_height)
    # Never upscale. Force even width/height for yuv420p.
    scale = (
        f"scale=w='if(gt(ih,{h}),-2,iw)':h='if(gt(ih,{h}),{h},ih)',"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )
    if preset.max_fps:
        return f"fps={preset.max_fps},{scale}"
    return scale


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    preset: Preset,
    *,
    duration: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
    progress_url: str = "pipe:1",
) -> list[str]:
    cmd: list[str] = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        preset.codec,
        "-preset",
        preset.ffmpeg_preset,
        "-pix_fmt",
        "yuv420p",
        "-vf",
        build_vf(preset),
        "-c:a",
        "aac",
        "-b:a",
        preset.audio_bitrate,
        "-ac",
        "2",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "-metadata",
        "comment=compressed by compressor-bot",
    ]
    if preset.codec == "libx265":
        cmd.extend(["-tag:v", "hvc1", "-x265-params", "log-level=error"])

    if preset.target_mb and duration > 0:
        br = target_video_bitrate_k(duration, preset.target_mb, preset.audio_bitrate)
        cmd.extend(
            [
                "-b:v",
                f"{br}k",
                "-maxrate",
                f"{int(br * 1.15)}k",
                "-bufsize",
                f"{int(br * 2)}k",
            ]
        )
    elif preset.crf is not None:
        cmd.extend(["-crf", str(preset.crf)])
    else:
        cmd.extend(["-crf", "23"])

    cmd.extend(["-progress", progress_url, "-nostats", str(output_path)])
    return cmd


def build_thumbnail_command(
    input_path: Path,
    output_path: Path,
    *,
    at_sec: float = 1.0,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    stamp = max(0.0, at_sec)
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-ss",
        f"{stamp:.2f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-2",
        "-q:v",
        "4",
        str(output_path),
    ]


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(
    r"Stream #\d+:\d+(?:\[.*?\])?(?:\([^)]*\))?:\s*Video:\s*([^,\s]+).*?,\s*(\d{2,5})x(\d{2,5})"
)
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:fps|tbr)")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*Audio:")
_ROTATE_RE = re.compile(r"rotate\s*:\s*(-?\d+)")
_SIZE_RE = re.compile(r"bitrate:\s*N/A|Duration:")


def parse_ffmpeg_probe(stderr: str, file_size: int = 0) -> Probe:
    probe = Probe(size=file_size)
    match = _DURATION_RE.search(stderr)
    if match:
        h, m, s = match.groups()
        probe.duration = int(h) * 3600 + int(m) * 60 + float(s)
    vmatch = _VIDEO_RE.search(stderr)
    if vmatch:
        probe.codec = vmatch.group(1)
        probe.width = int(vmatch.group(2))
        probe.height = int(vmatch.group(3))
    fmatch = _FPS_RE.search(stderr)
    if fmatch:
        probe.fps = float(fmatch.group(1))
    probe.has_audio = bool(_AUDIO_RE.search(stderr))
    rmatch = _ROTATE_RE.search(stderr)
    if rmatch:
        probe.rotation = int(rmatch.group(1)) % 360
    return probe


def probe_video(path: Path, *, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str | None = None) -> Probe:
    size = path.stat().st_size if path.exists() else 0
    probe_bin = ffprobe_bin or shutil.which("ffprobe")
    if probe_bin:
        try:
            result = __import__("subprocess").run(
                [
                    probe_bin,
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return _probe_from_ffprobe_json(result.stdout, size)
        except (OSError, json.JSONDecodeError, ValueError):
            logger.warning("ffprobe failed, falling back to ffmpeg -i")

    result = __import__("subprocess").run(
        [ffmpeg_bin, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # ffmpeg -i writes probe info to stderr and exits non-zero.
    return parse_ffmpeg_probe(result.stderr or "", size)


def _probe_from_ffprobe_json(raw: str, size: int) -> Probe:
    data = json.loads(raw)
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    rotate = 0
    tags = video.get("tags") or {}
    if "rotate" in tags:
        try:
            rotate = int(tags["rotate"])
        except ValueError:
            rotate = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            try:
                rotate = int(side["rotation"])
            except (TypeError, ValueError):
                pass
    return Probe(
        duration=float(fmt.get("duration") or video.get("duration") or 0) or 0.0,
        size=int(fmt.get("size") or size or 0),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        codec=str(video.get("codec_name") or "unknown"),
        fps=parse_frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        has_audio=audio is not None,
        rotation=rotate % 360,
    )


def parse_progress_line(line: str, duration: float) -> float | None:
    """Return 0-1 progress from an ffmpeg -progress key=value line."""
    if duration <= 0:
        return None
    line = line.strip()
    if line.startswith("out_time_ms="):
        raw = line.split("=", 1)[1]
        if raw.isdigit():
            return min(0.99, (int(raw) / 1_000_000) / duration)
    if line.startswith("out_time="):
        stamp = line.split("=", 1)[1]
        seconds = _hms_to_seconds(stamp)
        if seconds is not None:
            return min(0.99, seconds / duration)
    if line == "progress=end":
        return 1.0
    return None


def _hms_to_seconds(stamp: str) -> float | None:
    # 00:00:12.340000
    parts = stamp.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None


def progress_bar(fraction: float, width: int = 16) -> str:
    frac = min(1.0, max(0.0, fraction))
    filled = int(round(frac * width))
    filled = min(width, max(0, filled))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {int(frac * 100):3d}%"


async def compress_video(
    input_path: Path,
    output_path: Path,
    preset: Preset,
    *,
    duration: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
    timeout: float = 900,
    cancel_event: asyncio.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> CompressResult:
    original = input_path.stat().st_size if input_path.exists() else 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_command(
        input_path, output_path, preset, duration=duration, ffmpeg_bin=ffmpeg_bin
    )
    logger.info("ffmpeg %s", " ".join(cmd))

    loop = asyncio.get_running_loop()
    started = loop.time()
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    last_emit = 0.0

    async def _maybe_progress(frac: float) -> None:
        nonlocal last_emit
        now = loop.time()
        if frac < 1 and now - last_emit < 1.2:
            return
        last_emit = now
        if on_progress:
            result = on_progress(frac)
            if asyncio.iscoroutine(result):
                await result

    async def _pump_stdout() -> None:
        assert process.stdout is not None
        buffer = b""
        while True:
            chunk = await process.stdout.read(256)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                frac = parse_progress_line(line.decode("utf-8", "replace"), duration)
                if frac is not None:
                    await _maybe_progress(frac)

    stdout_task = asyncio.create_task(_pump_stdout())
    stderr_task = asyncio.create_task(process.stderr.read() if process.stderr else asyncio.sleep(0, result=b""))

    try:
        while True:
            if cancel_event and cancel_event.is_set():
                process.kill()
                await process.wait()
                raise JobCancelled()
            try:
                await asyncio.wait_for(process.wait(), timeout=0.4)
                break
            except asyncio.TimeoutError:
                if loop.time() - started > timeout:
                    process.kill()
                    await process.wait()
                    return CompressResult(
                        ok=False,
                        output=None,
                        elapsed=loop.time() - started,
                        original_size=original,
                        compressed_size=0,
                        error="encode timed out",
                    )
        await stdout_task
        stderr = await stderr_task
        elapsed = loop.time() - started
        if process.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            tail = (stderr or b"").decode("utf-8", "replace")[-1500:]
            logger.error("ffmpeg failed (%s): %s", process.returncode, tail)
            return CompressResult(
                ok=False,
                output=None,
                elapsed=elapsed,
                original_size=original,
                compressed_size=0,
                error="ffmpeg failed",
            )
        compressed = output_path.stat().st_size
        skipped = compressed >= original and original > 0
        return CompressResult(
            ok=True,
            output=output_path,
            elapsed=elapsed,
            original_size=original,
            compressed_size=compressed,
            skipped_larger=skipped,
        )
    except JobCancelled:
        stdout_task.cancel()
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def make_thumbnail(
    input_path: Path,
    output_path: Path,
    *,
    duration: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
) -> Path | None:
    at = 1.0 if duration <= 0 else min(duration * 0.15, max(0.4, duration - 0.2))
    cmd = build_thumbnail_command(input_path, output_path, at_sec=at, ffmpeg_bin=ffmpeg_bin)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return output_path
    return None


def estimate_output_dims(probe: Probe, preset: Preset) -> tuple[int, int]:
    w = probe.display_width or probe.width
    h = probe.display_height or probe.height
    if w <= 0 or h <= 0:
        return 0, 0
    max_h = preset.max_height
    if h > max_h:
        scale = max_h / h
        w = int(w * scale)
        h = max_h
    w -= w % 2
    h -= h % 2
    return max(2, w), max(2, h)
