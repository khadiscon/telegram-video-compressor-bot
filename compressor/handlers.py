"""Telegram handlers: commands, incoming media, callbacks."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram import InputFile, Message, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from compressor.config import Config
from compressor.engine import (
    DEFAULT_PRESET,
    PRESETS,
    JobCancelled,
    Preset,
    PresetId,
    Probe,
    compress_video,
    estimate_output_dims,
    ffmpeg_available,
    format_duration,
    human_size,
    make_thumbnail,
    probe_video,
    resolve_preset,
)
from compressor.jobs import Job, JobManager
from compressor.keyboards import preset_keyboard, settings_keyboard
from compressor.store import Store
from compressor import texts

logger = logging.getLogger("compressor.handlers")

VIDEO_MIMES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
    "video/x-msvideo",
    "video/mpeg",
    "video/3gpp",
    "video/3gpp2",
    "video/x-m4v",
}


@dataclass
class PendingMedia:
    file_id: str
    file_unique_id: str
    file_name: str
    file_size: int
    kind: str  # video | document | note | animation
    width: int = 0
    height: int = 0
    duration: int = 0


def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _store(context: ContextTypes.DEFAULT_TYPE) -> Store:
    return context.application.bot_data["store"]


def _jobs(context: ContextTypes.DEFAULT_TYPE) -> JobManager:
    return context.application.bot_data["jobs"]


def _allowed(user_id: int, cfg: Config) -> bool:
    if user_id and cfg.owner_id and user_id == cfg.owner_id:
        return True
    if cfg.private_mode:
        return user_id in cfg.allowed_user_ids
    return True


async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    cfg = _cfg(context)
    if not _allowed(user.id, cfg):
        if update.effective_message:
            await update.effective_message.reply_text("This bot is private.")
        return False
    rec = _store(context).touch(
        user.id, username=user.username or "", now=time.time()
    )
    if rec.banned:
        if update.effective_message:
            await update.effective_message.reply_text("You are blocked from this bot.")
        return False
    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _guard(update, context):
        return
    await update.effective_message.reply_text(
        texts.start_text(update.effective_user.first_name or "", _cfg(context)),
        parse_mode=ParseMode.HTML,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    if not await _guard(update, context):
        return
    await update.effective_message.reply_text(
        texts.help_text(_cfg(context)), parse_mode=ParseMode.HTML
    )


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    if not await _guard(update, context):
        return
    await update.effective_message.reply_text(texts.privacy_text(), parse_mode=ParseMode.HTML)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _guard(update, context):
        return
    user = _store(context).get_user(update.effective_user.id)
    await update.effective_message.reply_text(
        texts.settings_text(user),
        parse_mode=ParseMode.HTML,
        reply_markup=settings_keyboard(user.ask_each, user.preset),
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _guard(update, context):
        return
    store = _store(context)
    user = store.get_user(update.effective_user.id)
    show_global = _cfg(context).owner_id == update.effective_user.id
    await update.effective_message.reply_text(
        texts.stats_text(user, store.stats() if show_global else None),
        parse_mode=ParseMode.HTML,
    )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _guard(update, context):
        return
    job = _jobs(context).get(update.effective_user.id)
    if not job:
        await update.effective_message.reply_text("No job in progress.")
        return
    pos = _jobs(context).position(update.effective_user.id)
    await update.effective_message.reply_text(
        f"State: {job.state}\nQueue position: {pos}\nProgress: {int(job.progress * 100)}%"
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _guard(update, context):
        return
    if _jobs(context).request_cancel(update.effective_user.id):
        await update.effective_message.reply_text("Stopping the current job.")
    else:
        await update.effective_message.reply_text("Nothing to cancel.")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    cfg = _cfg(context)
    if not cfg.owner_id or update.effective_user.id != cfg.owner_id:
        return
    await update.effective_message.reply_text(
        texts.admin_stats(_store(context).stats(), _jobs(context).active_count()),
        parse_mode=ParseMode.HTML,
    )


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _moderation(update, context, banned=True)


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _moderation(update, context, banned=False)


async def _moderation(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, banned: bool
) -> None:
    if not update.effective_user or not update.effective_message:
        return
    cfg = _cfg(context)
    if not cfg.owner_id or update.effective_user.id != cfg.owner_id:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /ban <user_id> or /unban <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("user_id must be a number.")
        return
    _store(context).set_banned(target, banned)
    verb = "Banned" if banned else "Unbanned"
    await update.effective_message.reply_text(f"{verb} {target}.")


def extract_media(message: Message) -> PendingMedia | None:
    if message.video:
        v = message.video
        return PendingMedia(
            file_id=v.file_id,
            file_unique_id=v.file_unique_id,
            file_name=getattr(v, "file_name", None) or f"video_{v.file_unique_id}.mp4",
            file_size=v.file_size or 0,
            kind="video",
            width=v.width or 0,
            height=v.height or 0,
            duration=v.duration or 0,
        )
    if message.video_note:
        n = message.video_note
        return PendingMedia(
            file_id=n.file_id,
            file_unique_id=n.file_unique_id,
            file_name=f"note_{n.file_unique_id}.mp4",
            file_size=n.file_size or 0,
            kind="note",
            width=n.length or 0,
            height=n.length or 0,
            duration=n.duration or 0,
        )
    if message.animation:
        a = message.animation
        return PendingMedia(
            file_id=a.file_id,
            file_unique_id=a.file_unique_id,
            file_name=a.file_name or f"anim_{a.file_unique_id}.mp4",
            file_size=a.file_size or 0,
            kind="animation",
            width=a.width or 0,
            height=a.height or 0,
            duration=a.duration or 0,
        )
    if message.document:
        d = message.document
        mime = (d.mime_type or "").lower()
        name = (d.file_name or "").lower()
        looks_video = mime in VIDEO_MIMES or mime.startswith("video/") or name.endswith(
            (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg", ".3gp")
        )
        if not looks_video:
            return None
        return PendingMedia(
            file_id=d.file_id,
            file_unique_id=d.file_unique_id,
            file_name=d.file_name or f"doc_{d.file_unique_id}.mp4",
            file_size=d.file_size or 0,
            kind="document",
        )
    return None


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return
    if chat.type != ChatType.PRIVATE:
        return
    if not await _guard(update, context):
        return

    media = extract_media(message)
    if not media:
        return

    cfg = _cfg(context)
    if media.file_size and media.file_size > cfg.download_limit_bytes:
        await message.reply_text(texts.too_large_download(media.file_size, cfg.download_limit_mb))
        return

    rec = _store(context).get_user(user.id)
    if rec.ask_each:
        context.user_data["pending"] = media
        await message.reply_text(
            texts.pick_preset_text(media.file_name, media.file_size),
            parse_mode=ParseMode.HTML,
            reply_markup=preset_keyboard("run"),
            reply_to_message_id=message.message_id,
        )
        return

    await run_job(update, context, media, rec.preset, reply_to=message.message_id)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    if not await _guard(update, context):
        return

    data = query.data or ""
    if data.startswith("set:"):
        await _on_settings_callback(update, context, data.split(":", 1)[1])
        return
    if data.startswith("run:"):
        action = data.split(":", 1)[1]
        if action == "cancel":
            context.user_data.pop("pending", None)
            try:
                await query.edit_message_text("Cancelled.")
            except BadRequest:
                pass
            return
        pending: PendingMedia | None = context.user_data.get("pending")
        if not pending:
            try:
                await query.edit_message_text("That video expired. Send it again.")
            except BadRequest:
                pass
            return
        if action not in PRESETS:
            return
        context.user_data.pop("pending", None)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        await run_job(
            update,
            context,
            pending,
            action,  # type: ignore[arg-type]
            status_message=query.message if isinstance(query.message, Message) else None,
        )


async def _on_settings_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    user = update.effective_user
    query = update.callback_query
    if not user or not query:
        return
    store = _store(context)
    rec = store.get_user(user.id)
    if action == "toggle_ask":
        rec = store.update_user(user.id, ask_each=not rec.ask_each)
    elif action in PRESETS:
        rec = store.update_user(user.id, preset=action)
    try:
        await query.edit_message_text(
            texts.settings_text(rec),
            parse_mode=ParseMode.HTML,
            reply_markup=settings_keyboard(rec.ask_each, rec.preset),
        )
    except BadRequest:
        pass


async def run_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    media: PendingMedia,
    preset_id: PresetId,
    *,
    reply_to: int | None = None,
    status_message: Message | None = None,
) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    cfg = _cfg(context)
    jobs = _jobs(context)
    preset = resolve_preset(preset_id)

    job = Job(user_id=user.id, chat_id=chat.id, status_message_id=None)
    ok, reason = await jobs.begin(job)
    if not ok:
        target = status_message or update.effective_message
        if target:
            if status_message:
                await status_message.edit_text(reason)
            else:
                await target.reply_text(reason)
        return

    status = status_message
    job_dir: Path | None = None
    try:
        if status is None and update.effective_message:
            status = await update.effective_message.reply_text(
                texts.progress_text("Queued."),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to,
            )
        if status:
            job.status_message_id = status.message_id

        async with jobs.semaphore:
            if job.cancel.is_set():
                raise JobCancelled()
            job.state = "downloading"
            await _edit(status, texts.progress_text("Downloading."))

            job_dir = cfg.temp_dir / f"{user.id}_{int(time.time())}"
            job_dir.mkdir(parents=True, exist_ok=True)
            src = job_dir / _safe_name(media.file_name)
            dst = job_dir / f"compressed_{src.stem}.mp4"
            thumb_path = job_dir / "thumb.jpg"

            tg_file = await context.bot.get_file(media.file_id)
            await tg_file.download_to_drive(custom_path=str(src))
            if job.cancel.is_set():
                raise JobCancelled()

            job.state = "probing"
            await _edit(status, texts.progress_text("Analyzing."))
            probe = probe_video(src, ffmpeg_bin=cfg.ffmpeg_bin, ffprobe_bin=cfg.ffprobe_bin)

            job.state = "encoding"
            await _edit(
                status,
                texts.progress_text(
                    f"Encoding · {preset.label}",
                    0.0,
                    f"{human_size(src.stat().st_size)} · {format_duration(probe.duration)}",
                ),
            )

            async def on_progress(frac: float) -> None:
                job.progress = frac
                await _edit(
                    status,
                    texts.progress_text(f"Encoding · {preset.label}", frac),
                )

            result = await compress_video(
                src,
                dst,
                preset,
                duration=probe.duration,
                ffmpeg_bin=cfg.ffmpeg_bin,
                timeout=cfg.job_timeout_sec,
                cancel_event=job.cancel,
                on_progress=on_progress,
            )
            if not result.ok or not result.output:
                await _edit(status, result.error or "Encode failed.")
                return
            if result.skipped_larger:
                await _edit(status, texts.result_caption(result, preset, probe))
                return
            if result.compressed_size > cfg.upload_limit_bytes:
                await _edit(
                    status, texts.too_large_upload(result.compressed_size, cfg.upload_limit_mb)
                )
                return

            job.state = "uploading"
            await _edit(status, texts.progress_text("Uploading.", 1.0))
            thumb = await make_thumbnail(
                result.output, thumb_path, duration=probe.duration, ffmpeg_bin=cfg.ffmpeg_bin
            )
            out_w, out_h = estimate_output_dims(probe, preset)
            caption = texts.result_caption(result, preset, probe)

            kwargs: dict[str, Any] = {
                "chat_id": chat.id,
                "caption": caption,
                "parse_mode": ParseMode.HTML,
                "supports_streaming": True,
                "read_timeout": 180,
                "write_timeout": 180,
                "connect_timeout": 60,
            }
            if reply_to:
                kwargs["reply_to_message_id"] = reply_to
            if out_w and out_h:
                kwargs["width"] = out_w
                kwargs["height"] = out_h
            if probe.duration:
                kwargs["duration"] = int(probe.duration)
            if thumb:
                kwargs["thumbnail"] = InputFile(thumb.open("rb"), filename="thumb.jpg")

            with result.output.open("rb") as handle:
                kwargs["video"] = InputFile(handle, filename=result.output.name)
                await context.bot.send_video(**kwargs)

            _store(context).record_job(user.id, result.original_size, result.compressed_size)
            if status:
                try:
                    await status.delete()
                except TelegramError:
                    pass
            logger.info(
                "user=%s %s → %s (%.0f%%) preset=%s %.1fs",
                user.id,
                human_size(result.original_size),
                human_size(result.compressed_size),
                result.ratio * 100,
                preset.id,
                result.elapsed,
            )
    except JobCancelled:
        if status:
            await _edit(status, "Cancelled.")
    except TelegramError as exc:
        logger.exception("telegram error user=%s", user.id)
        if status:
            await _edit(status, f"Telegram error: {exc.message}")
    except Exception:
        logger.exception("job failed user=%s", user.id)
        if status:
            await _edit(status, "Something went wrong while compressing.")
    finally:
        await jobs.finish(user.id)
        if job_dir and job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in Path(name).name)
    if not cleaned.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg", ".3gp")):
        cleaned = (cleaned or "video") + ".mp4"
    return cleaned[:120]


async def _edit(message: Message | None, text: str) -> None:
    if not message:
        return
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML)
    except BadRequest:
        pass
    except TelegramError:
        logger.debug("status edit failed", exc_info=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("update failed", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An internal error occurred. Try again in a moment."
            )
        except TelegramError:
            pass


def ffmpeg_ready(cfg: Config) -> bool:
    return ffmpeg_available(cfg.ffmpeg_bin)
