"""Application entry: wire handlers and start polling."""

from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from compressor.config import Config, load_config
from compressor.handlers import (
    admin_command,
    ban_command,
    callback_handler,
    cancel_command,
    error_handler,
    ffmpeg_ready,
    help_command,
    media_handler,
    privacy_command,
    queue_command,
    settings_command,
    start_command,
    stats_command,
    unban_command,
)
from compressor.jobs import JobManager
from compressor.store import Store

logger = logging.getLogger("compressor")

LARGE_IO_TIMEOUT = 3600


def configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=logging.INFO,
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def build_application(cfg: Config) -> Application:
    builder = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .concurrent_updates(True)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .media_write_timeout(LARGE_IO_TIMEOUT)
        .pool_timeout(30)
    )
    if cfg.api_base_url:
        builder = builder.base_url(cfg.api_base_url)
    if cfg.api_file_url:
        builder = builder.base_file_url(cfg.api_file_url)
    if cfg.local_mode:
        builder = builder.local_mode(True)
    app = builder.build()

    cfg.temp_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    app.bot_data["config"] = cfg
    app.bot_data["store"] = Store(cfg.data_dir / "store.json")
    app.bot_data["jobs"] = JobManager(cfg.max_concurrent_jobs, cfg.per_user_limit)

    media_filter = (
        (filters.VIDEO | filters.VIDEO_NOTE | filters.ANIMATION | filters.Document.VIDEO)
        & filters.ChatType.PRIVATE
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("privacy", privacy_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(media_filter, media_handler))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    configure_logging()
    cfg = load_config()
    if not cfg.bot_token:
        logger.critical(
            "BOT_TOKEN is missing. Copy .env.example to .env and paste the token from @BotFather."
        )
        raise SystemExit(2)
    if not ffmpeg_ready(cfg):
        logger.critical(
            "ffmpeg not found (%s). Install ffmpeg with libx264 + aac, or set FFMPEG_BIN.",
            cfg.ffmpeg_bin,
        )
        raise SystemExit(1)

    logger.info(
        "starting compressor  concurrent=%s  local_api=%s  download=%sMB  upload=%sMB  temp=%s",
        cfg.max_concurrent_jobs,
        cfg.local_mode,
        cfg.download_limit_mb,
        cfg.upload_limit_mb,
        cfg.temp_dir,
    )
    application = build_application(cfg)
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
