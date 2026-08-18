"""In-memory job queue: global concurrency + one active job per user."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

JobState = Literal["queued", "downloading", "probing", "encoding", "uploading"]


@dataclass
class Job:
    user_id: int
    chat_id: int
    status_message_id: int | None
    state: JobState = "queued"
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)

    def cancel_now(self) -> None:
        self.cancel.set()


class JobManager:
    def __init__(self, max_concurrent: int, per_user_limit: int = 1) -> None:
        self.max_concurrent = max_concurrent
        self.per_user_limit = per_user_limit
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[int, Job] = {}
        self._lock = asyncio.Lock()

    async def begin(self, job: Job) -> tuple[bool, str]:
        async with self._lock:
            existing = self._jobs.get(job.user_id)
            if existing and not existing.cancel.is_set():
                return False, "You already have a job in progress. Send /cancel first."
            self._jobs[job.user_id] = job
            return True, ""

    def get(self, user_id: int) -> Job | None:
        return self._jobs.get(user_id)

    def position(self, user_id: int) -> int:
        job = self._jobs.get(user_id)
        if not job:
            return 0
        waiting = [
            j
            for j in self._jobs.values()
            if j.state == "queued" and j.created_at <= job.created_at
        ]
        return max(1, len(waiting))

    def active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if not j.cancel.is_set())

    async def finish(self, user_id: int) -> None:
        async with self._lock:
            self._jobs.pop(user_id, None)

    def request_cancel(self, user_id: int) -> bool:
        job = self._jobs.get(user_id)
        if not job:
            return False
        job.cancel_now()
        return True
