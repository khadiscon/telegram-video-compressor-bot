"""JSON persistence for user settings and aggregate stats."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from compressor.engine import DEFAULT_PRESET, PresetId


@dataclass
class UserRecord:
    user_id: int
    preset: PresetId = DEFAULT_PRESET
    ask_each: bool = True
    videos: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    banned: bool = False
    username: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0

    @property
    def bytes_saved(self) -> int:
        return max(0, self.bytes_in - self.bytes_out)


@dataclass
class GlobalStats:
    videos: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    users: int = 0


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._users: dict[int, UserRecord] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in raw.get("users") or []:
            try:
                uid = int(item["user_id"])
                preset = item.get("preset") or DEFAULT_PRESET
                if preset not in {"light", "medium", "strong", "ultra", "tg8", "tg2"}:
                    preset = DEFAULT_PRESET
                self._users[uid] = UserRecord(
                    user_id=uid,
                    preset=preset,  # type: ignore[arg-type]
                    ask_each=bool(item.get("ask_each", True)),
                    videos=int(item.get("videos") or 0),
                    bytes_in=int(item.get("bytes_in") or 0),
                    bytes_out=int(item.get("bytes_out") or 0),
                    banned=bool(item.get("banned", False)),
                    username=str(item.get("username") or ""),
                    first_seen=float(item.get("first_seen") or 0),
                    last_seen=float(item.get("last_seen") or 0),
                )
            except (KeyError, TypeError, ValueError):
                continue

    def _dump(self) -> None:
        payload: dict[str, Any] = {
            "users": [asdict(u) for u in self._users.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get_user(self, user_id: int) -> UserRecord:
        with self._lock:
            if user_id not in self._users:
                self._users[user_id] = UserRecord(user_id=user_id)
            return self._users[user_id]

    def touch(self, user_id: int, *, username: str = "", now: float = 0.0) -> UserRecord:
        with self._lock:
            rec = self._users.get(user_id) or UserRecord(user_id=user_id)
            if username:
                rec.username = username
            if rec.first_seen == 0 and now:
                rec.first_seen = now
            if now:
                rec.last_seen = now
            self._users[user_id] = rec
            self._dump()
            return rec

    def update_user(self, user_id: int, **changes: Any) -> UserRecord:
        with self._lock:
            rec = self._users.get(user_id) or UserRecord(user_id=user_id)
            for key, value in changes.items():
                if hasattr(rec, key):
                    setattr(rec, key, value)
            self._users[user_id] = rec
            self._dump()
            return rec

    def record_job(self, user_id: int, bytes_in: int, bytes_out: int) -> None:
        with self._lock:
            rec = self._users.get(user_id) or UserRecord(user_id=user_id)
            rec.videos += 1
            rec.bytes_in += max(0, bytes_in)
            rec.bytes_out += max(0, bytes_out)
            self._users[user_id] = rec
            self._dump()

    def set_banned(self, user_id: int, banned: bool) -> UserRecord:
        return self.update_user(user_id, banned=banned)

    def all_user_ids(self) -> list[int]:
        with self._lock:
            return list(self._users.keys())

    def stats(self) -> GlobalStats:
        with self._lock:
            videos = sum(u.videos for u in self._users.values())
            bin_ = sum(u.bytes_in for u in self._users.values())
            bout = sum(u.bytes_out for u in self._users.values())
            return GlobalStats(
                videos=videos,
                bytes_in=bin_,
                bytes_out=bout,
                users=len(self._users),
            )
