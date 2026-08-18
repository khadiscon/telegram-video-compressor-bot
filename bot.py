#!/usr/bin/env python3
"""
Sophisticated Telegram Video Compressor Bot

A production-ready bot that receives videos (sent or forwarded),
compresses them using FFmpeg with configurable quality presets,
and returns the optimized result.

Key constraints (Telegram Bot API):
- Download limit via getFile: 20 MB
- Upload limit: 50 MB

Requires: FFmpeg with libx264 and libx265 support.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Message,
)
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required. Create a .env file.")

# Maximum concurrent compression jobs (protects CPU/RAM)
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))

# Temporary directory for downloads and processing
TEMP_ROOT = Path(os.getenv("TEMP_DIR", tempfile.gettempdir())) / "tg_video_compressor"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("VideoCompressorBot")

# ---------------------------------------------------------------------------
# Compression Presets
# ---------------------------------------------------------------------------

class Codec(str, Enum):
    H264 = "libx264"
    H265 = "libx265"


class Preset(str, Enum):
    LIGHT = "light"      # Higher quality, larger size
    MEDIUM = "medium"    # Balanced (default)
    STRONG = "strong"    # Aggressive compression
    ULTRA = "ultra"      # Maximum size reduction


@dataclass
class CompressionSettings:
    """User-configurable or default compression parameters."""
    codec: Codec = Codec.H264
    preset: Preset = Preset.MEDIUM
    # CRF: lower = better quality / larger file. Typical 18-28 for x264, 22-32 for x265
    crf: int = 23
    # Optional max height (0 = keep original)
    max_height: int = 0
    # Audio bitrate in kbps
    audio_bitrate: str = "128k"
    # FFmpeg encoding preset (ultrafast ... veryslow)
    ffmpeg_preset: str = "medium"
    # Keep original audio stream when possible (copy)
    copy_audio: bool = False


DEFAULT_SETTINGS = CompressionSettings()

PRESET_MAP = {
    Preset.LIGHT: CompressionSettings(codec=Codec.H264, crf=20, ffmpeg_preset="medium"),
    Preset.MEDIUM: CompressionSettings(codec=Codec.H264, crf=23, ffmpeg_preset="medium"),
    Preset.STRONG: CompressionSettings(codec=Codec.H264, crf=28, ffmpeg_preset="fast"),
    Preset.ULTRA: CompressionSettings(codec=Codec.H265, crf=28, ffmpeg_preset="fast", max_height=720),
}


# ---------------------------------------------------------------------------
# Job concurrency control
# ---------------------------------------------------------------------------

job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
active_jobs: dict[int, str] = {}  # user_id -> status description


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------

def check_ffmpeg() -> bool:
    """Verify FFmpeg and required codecs are available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        # Basic check for codecs
        codecs = subprocess.run(
            ["ffmpeg", "-codecs"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "libx264" in codecs.stdout and "libx265" in codecs.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def probe_video(path: Path) -> dict:
    """Extract basic media information using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {}
        import json
        data = json.loads(result.stdout)
        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )
        format_info = data.get("format", {})
        return {
            "duration": float(format_info.get("duration", 0)),
            "size": int(format_info.get("size", 0)),
            "bitrate": int(format_info.get("bit_rate", 0)),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name", "unknown"),
            "fps": eval(video_stream.get("r_frame_rate", "0/1")) if "/" in str(video_stream.get("r_frame_rate", "0")) else 0,
        }
    except Exception as exc:
        logger.warning("ffprobe failed: %s", exc)
        return {}


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    settings: CompressionSettings,
) -> list[str]:
    """Construct an optimized FFmpeg command for video compression."""
    cmd = [
        "ffmpeg",
        "-y",  # overwrite
        "-i", str(input_path),
        "-c:v", settings.codec.value,
        "-crf", str(settings.crf),
        "-preset", settings.ffmpeg_preset,
        "-pix_fmt", "yuv420p",  # maximum compatibility
        "-movflags", "+faststart",  # progressive download / streaming
    ]

    # Optional resolution limit (maintain aspect ratio)
    if settings.max_height > 0:
        cmd.extend(["-vf", f"scale=-2:{settings.max_height}"])

    # Audio handling
    if settings.copy_audio:
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", settings.audio_bitrate, "-ac", "2"])

    # H.265 specific (better compatibility on some devices)
    if settings.codec == Codec.H265:
        cmd.extend(["-tag:v", "hvc1"])

    cmd.append(str(output_path))
    return cmd


async def compress_video(
    input_path: Path,
    output_path: Path,
    settings: CompressionSettings,
    progress_callback=None,
) -> bool:
    """
    Run FFmpeg compression asynchronously.
    Returns True on success.
    """
    cmd = build_ffmpeg_command(input_path, output_path, settings)
    logger.info("FFmpeg command: %s", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Simple wait; for real progress one would parse -progress pipe
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error("FFmpeg failed (code %s): %s", process.returncode, stderr.decode(errors="ignore")[-2000:])
        return False

    return output_path.exists() and output_path.stat().st_size > 0


def human_size(num_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Bot handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message and brief instructions."""
    user = update.effective_user
    text = (
        f"Welcome, {user.first_name or 'User'}.\n\n"
        "This is a sophisticated video compression bot.\n\n"
        "<b>How to use</b>\n"
        "• Send or forward any video (or video document) directly to this chat.\n"
        "• The bot will automatically compress it and return the result.\n\n"
        "<b>Limits</b>\n"
        "• Maximum download size: <b>20 MB</b> (Telegram Bot API restriction).\n"
        "• Maximum upload size: <b>50 MB</b>.\n\n"
        "Use /help for detailed commands and /settings to adjust quality presets."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detailed help."""
    text = (
        "<b>Available Commands</b>\n\n"
        "/start – Introduction and basic usage\n"
        "/help – This message\n"
        "/settings – View or change compression presets\n"
        "/status – Check current job status\n\n"
        "<b>Automatic Processing</b>\n"
        "Any video or video file (document) sent or forwarded to this bot "
        "in a private chat will be processed automatically.\n\n"
        "<b>Presets</b>\n"
        "• <b>Light</b> – Higher quality, moderate size reduction (CRF 20)\n"
        "• <b>Medium</b> – Balanced (default, CRF 23)\n"
        "• <b>Strong</b> – Aggressive size reduction (CRF 28)\n"
        "• <b>Ultra</b> – Maximum compression using H.265 + 720p limit\n\n"
        "<b>Technical Notes</b>\n"
        "• Output is always MP4 (H.264 or H.265 + AAC).\n"
        "• Metadata is optimized for streaming (+faststart).\n"
        "• Temporary files are cleaned after processing."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current settings and allow preset selection."""
    user_data = context.user_data
    current = user_data.get("settings", DEFAULT_SETTINGS)

    text = (
        "<b>Current Compression Settings</b>\n\n"
        f"Preset: <code>{current.preset.value if hasattr(current, 'preset') else 'custom'}</code>\n"
        f"Codec: <code>{current.codec.value}</code>\n"
        f"CRF: <code>{current.crf}</code>\n"
        f"Max height: <code>{current.max_height or 'original'}</code>\n"
        f"FFmpeg preset: <code>{current.ffmpeg_preset}</code>\n\n"
        "Select a new preset:"
    )

    keyboard = [
        [
            InlineKeyboardButton("Light", callback_data="preset:light"),
            InlineKeyboardButton("Medium", callback_data="preset:medium"),
        ],
        [
            InlineKeyboardButton("Strong", callback_data="preset:strong"),
            InlineKeyboardButton("Ultra", callback_data="preset:ultra"),
        ],
        [InlineKeyboardButton("Reset to defaults", callback_data="preset:reset")],
    ]
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle preset selection."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("preset:"):
        return

    choice = data.split(":", 1)[1]
    if choice == "reset":
        context.user_data["settings"] = DEFAULT_SETTINGS
        await query.edit_message_text("Settings reset to defaults (Medium / H.264 / CRF 23).")
        return

    try:
        preset = Preset(choice)
        new_settings = PRESET_MAP[preset]
        # Attach the preset name for display
        new_settings.preset = preset  # type: ignore
        context.user_data["settings"] = new_settings
        await query.edit_message_text(
            f"Preset updated to <b>{preset.value.title()}</b>.\n"
            f"Codec: {new_settings.codec.value} | CRF: {new_settings.crf}",
            parse_mode=ParseMode.HTML,
        )
    except ValueError:
        await query.edit_message_text("Invalid preset selected.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report active job status for the user."""
    user_id = update.effective_user.id
    status = active_jobs.get(user_id)
    if status:
        await update.message.reply_text(f"Current job status: {status}")
    else:
        await update.message.reply_text("No active compression job.")


async def process_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Core handler: download → probe → compress → upload → cleanup.
    Supports both Video and Document (video/*) messages.
    """
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if chat.type != ChatType.PRIVATE:
        # Optional: ignore groups or add admin-only logic
        return

    # Identify the media object
    video = message.video
    document = message.document
    file_id = None
    file_name = "video.mp4"
    file_size = 0

    if video:
        file_id = video.file_id
        file_size = video.file_size or 0
        file_name = getattr(video, "file_name", None) or f"video_{video.file_unique_id}.mp4"
    elif document and document.mime_type and document.mime_type.startswith("video/"):
        file_id = document.file_id
        file_size = document.file_size or 0
        file_name = document.file_name or f"video_{document.file_unique_id}.mp4"
    else:
        return  # Not a processable video

    # Enforce download limit
    if file_size > 20 * 1024 * 1024:
        await message.reply_text(
            "⚠️ The video exceeds the 20 MB download limit of the Telegram Bot API.\n"
            "Please compress it further on your device or use a local Bot API server deployment for larger files."
        )
        return

    user_id = user.id
    if user_id in active_jobs:
        await message.reply_text(
            "You already have a compression job in progress. Please wait for it to finish."
        )
        return

    # Acquire concurrency slot
    status_msg: Optional[Message] = None
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None

    try:
        async with job_semaphore:
            active_jobs[user_id] = "Queued / downloading…"
            status_msg = await message.reply_text(
                "📥 Downloading video…",
                reply_to_message_id=message.message_id,
            )

            # Create per-job temp directory
            job_dir = TEMP_ROOT / f"{user_id}_{int(time.time())}"
            job_dir.mkdir(parents=True, exist_ok=True)
            input_path = job_dir / file_name
            output_path = job_dir / f"compressed_{Path(file_name).stem}.mp4"

            # Download
            tg_file = await context.bot.get_file(file_id)
            await tg_file.download_to_drive(custom_path=str(input_path))

            active_jobs[user_id] = "Probing media…"
            await status_msg.edit_text("🔍 Analyzing video…")

            info = probe_video(input_path)
            original_size = input_path.stat().st_size

            # Prepare settings
            settings: CompressionSettings = context.user_data.get("settings", DEFAULT_SETTINGS)

            active_jobs[user_id] = "Compressing…"
            codec_name = "H.265 (HEVC)" if settings.codec == Codec.H265 else "H.264 (AVC)"
            await status_msg.edit_text(
                f"⚙️ Compressing with {codec_name} (CRF {settings.crf})…\n"
                f"Original size: {human_size(original_size)}"
            )

            start_ts = time.perf_counter()
            success = await compress_video(input_path, output_path, settings)
            elapsed = time.perf_counter() - start_ts

            if not success or not output_path.exists():
                await status_msg.edit_text(
                    "❌ Compression failed. The source may be corrupted or unsupported."
                )
                return

            compressed_size = output_path.stat().st_size
            ratio = (1 - compressed_size / original_size) * 100 if original_size else 0

            # Safety: do not send files larger than 50 MB
            if compressed_size > 50 * 1024 * 1024:
                await status_msg.edit_text(
                    f"❌ Compressed file is still {human_size(compressed_size)}, "
                    "which exceeds the 50 MB upload limit. Try a stronger preset."
                )
                return

            active_jobs[user_id] = "Uploading…"
            await status_msg.edit_text(
                f"📤 Uploading compressed video…\n"
                f"Original: {human_size(original_size)} → Compressed: {human_size(compressed_size)} "
                f"({ratio:.1f}% reduction)\n"
                f"Time: {elapsed:.1f}s"
            )

            # Prefer send_video for proper client playback; fall back to document if needed
            caption = (
                f"✅ Compression complete\n"
                f"• Size: {human_size(original_size)} → {human_size(compressed_size)} "
                f"({ratio:.1f}% smaller)\n"
                f"• Codec: {codec_name}\n"
                f"• Processing time: {elapsed:.1f}s"
            )
            if info.get("duration"):
                caption += f"\n• Duration: {format_duration(info['duration'])}"

            with output_path.open("rb") as f:
                await context.bot.send_video(
                    chat_id=chat.id,
                    video=InputFile(f, filename=output_path.name),
                    caption=caption,
                    supports_streaming=True,
                    reply_to_message_id=message.message_id,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=60,
                )

            await status_msg.delete()
            logger.info(
                "User %s | %s → %s (%.1f%%) in %.1fs",
                user_id,
                human_size(original_size),
                human_size(compressed_size),
                ratio,
                elapsed,
            )

    except TelegramError as te:
        logger.exception("Telegram API error for user %s", user_id)
        if status_msg:
            try:
                await status_msg.edit_text(f"❌ Telegram error: {te.message}")
            except Exception:
                pass
    except Exception as exc:
        logger.exception("Unexpected error processing video for user %s", user_id)
        if status_msg:
            try:
                await status_msg.edit_text(f"❌ Unexpected error: {type(exc).__name__}")
            except Exception:
                pass
    finally:
        active_jobs.pop(user_id, None)
        # Cleanup
        if input_path and input_path.parent.exists():
            try:
                shutil.rmtree(input_path.parent, ignore_errors=True)
            except Exception:
                pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An internal error occurred. Please try again later."
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not check_ffmpeg():
        logger.critical(
            "FFmpeg is not installed or lacks libx264/libx265. "
            "Install FFmpeg with full codec support before starting the bot."
        )
        raise SystemExit(1)

    logger.info("Starting Video Compressor Bot…")
    logger.info("Max concurrent jobs: %d", MAX_CONCURRENT_JOBS)
    logger.info("Temp directory: %s", TEMP_ROOT)

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("status", status_command))

    # Callback for settings
    application.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^preset:"))

    # Video + video documents
    application.add_handler(
        MessageHandler(
            (filters.VIDEO | filters.Document.VIDEO) & filters.ChatType.PRIVATE,
            process_video,
        )
    )

    application.add_error_handler(error_handler)

    # Run
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
