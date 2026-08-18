"""Runtime configuration. Token is required only when the bot actually starts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int | None
    max_concurrent_jobs: int
    per_user_limit: int
    temp_dir: Path
    data_dir: Path
    api_base_url: str | None
    api_file_url: str | None
    local_mode: bool
    download_limit_mb: int
    upload_limit_mb: int
    job_timeout_sec: int
    allowed_user_ids: frozenset[int]
    private_mode: bool
    ffmpeg_bin: str
    ffprobe_bin: str | None

    @property
    def download_limit_bytes(self) -> int:
        return self.download_limit_mb * 1024 * 1024

    @property
    def upload_limit_bytes(self) -> int:
        return self.upload_limit_mb * 1024 * 1024


def load_config() -> Config:
    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    owner_raw = (os.getenv("OWNER_ID") or os.getenv("BOT_OWNER_ID") or "").strip()
    owner_id = int(owner_raw) if owner_raw.isdigit() else None

    allowed: set[int] = set()
    raw_allow = os.getenv("ALLOWED_USER_IDS", "")
    for part in raw_allow.replace(" ", "").split(","):
        if part.isdigit():
            allowed.add(int(part))
    if owner_id:
        allowed.add(owner_id)

    api_base = (os.getenv("TELEGRAM_API_URL") or "").rstrip("/") or None
    api_file = (os.getenv("TELEGRAM_FILE_URL") or "").rstrip("/") or None
    local_mode = _bool("TELEGRAM_LOCAL_API", bool(api_base))

    if api_base and not api_base.endswith("/bot"):
        api_base = api_base + "/bot"
    if api_file and not api_file.endswith("/file/bot"):
        api_file = api_file + "/file/bot"

    temp_dir = Path(os.getenv("TEMP_DIR") or "/tmp/tg_video_compressor")
    data_dir = Path(os.getenv("DATA_DIR") or "./data")

    download_limit = _int("DOWNLOAD_LIMIT_MB", 2000 if local_mode else 20)
    upload_limit = _int("UPLOAD_LIMIT_MB", 2000 if local_mode else 50)

    return Config(
        bot_token=token,
        owner_id=owner_id,
        max_concurrent_jobs=max(1, _int("MAX_CONCURRENT_JOBS", 2)),
        per_user_limit=max(1, _int("PER_USER_LIMIT", 1)),
        temp_dir=temp_dir,
        data_dir=data_dir,
        api_base_url=api_base,
        api_file_url=api_file,
        local_mode=local_mode,
        download_limit_mb=download_limit,
        upload_limit_mb=upload_limit,
        job_timeout_sec=max(30, _int("JOB_TIMEOUT_SEC", 900)),
        allowed_user_ids=frozenset(allowed),
        private_mode=_bool("PRIVATE_MODE", False),
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=os.getenv("FFPROBE_BIN") or None,
    )
