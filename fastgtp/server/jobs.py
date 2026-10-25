"""In-memory jobs for long analyses.

Jobs live only in memory. A restart loses them, and clients see 404 for an
unknown job and submit it again. Finished jobs are dropped after a retention
period because clients are expected to store the results themselves.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from .analysis import AnalysisFailure
from .problems import ANALYSIS_TIMED_OUT, INTERNAL_ERROR

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]
JobRunner = Callable[[Callable[[int], None]], Awaitable[dict[str, Any]]]

_FINISHED: frozenset[str] = frozenset({"succeeded", "failed", "canceled"})


class QueueFull(Exception):
    """Raised when no more jobs can wait to run."""


class IdempotencyConflict(Exception):
    """Raised when an idempotency key is reused for a different request."""


@dataclass(slots=True)
class Job:
    """One analysis job and its outcome."""

    id: str
    fingerprint: str
    total: int
    created_at: datetime
    idempotency_key: str | None = None
    status: JobStatus = "queued"
    done: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    finished_monotonic: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def finished(self) -> bool:
        """Return whether the job has stopped for good."""
        return self.status in _FINISHED


class JobManager:
    """Run jobs a few at a time, in the order they were submitted."""

    def __init__(
        self,
        *,
        max_running: int,
        max_queued: int,
        timeout_seconds: float,
        retention_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_running = max_running
        self._max_queued = max_queued
        self._timeout_seconds = timeout_seconds
        self._retention_seconds = retention_seconds
        self._clock = clock
        # asyncio.Semaphore wakes waiters first in, first out.
        self._slots = asyncio.Semaphore(max_running)
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}

    def submit(
        self,
        runner: JobRunner,
        *,
        fingerprint: str,
        total: int,
        idempotency_key: str | None = None,
    ) -> Job:
        """Queue a job, or return the earlier job for the same idempotency key."""
        self._purge()
        if idempotency_key is not None and idempotency_key in self._by_key:
            existing = self._jobs[self._by_key[idempotency_key]]
            if existing.fingerprint != fingerprint:
                raise IdempotencyConflict(idempotency_key)
            return existing

        # A job counts as queued until its task first runs, so jobs that
        # will take a free slot right away do not count against the queue.
        free_slots = max(0, self._max_running - self.running_count)
        if self.queued_count - free_slots >= self._max_queued:
            raise QueueFull()

        job = Job(
            id=uuid.uuid4().hex,
            fingerprint=fingerprint,
            total=total,
            created_at=_utcnow(),
            idempotency_key=idempotency_key,
        )
        self._jobs[job.id] = job
        if idempotency_key is not None:
            self._by_key[idempotency_key] = job.id
        job.task = asyncio.create_task(self._run(job, runner))
        return job

    def get(self, job_id: str) -> Job | None:
        """Return a job that has not been dropped yet."""
        self._purge()
        return self._jobs.get(job_id)

    async def delete(self, job_id: str) -> bool:
        """Stop a job that has not finished, and forget the job.

        Returns whether the job existed.
        """
        job = self.get(job_id)
        if job is None:
            return False
        # Forgotten first, so its idempotency key cannot return it while
        # its engine is still being stopped.
        self._forget(job)
        if not job.finished and job.task is not None:
            job.task.cancel()
            # wait() leaves the job's cancellation inside the job, while a
            # cancellation of this caller still reaches it.
            await asyncio.wait({job.task})
        return True

    async def close(self) -> None:
        """Cancel every job that has not finished."""
        tasks = [job.task for job in self._jobs.values() if job.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def queued_count(self) -> int:
        """Return the number of jobs waiting to run."""
        return sum(1 for job in self._jobs.values() if job.status == "queued")

    @property
    def running_count(self) -> int:
        """Return the number of jobs running now."""
        return sum(1 for job in self._jobs.values() if job.status == "running")

    async def _run(self, job: Job, runner: JobRunner) -> None:
        try:
            async with self._slots:
                job.status = "running"
                job.started_at = _utcnow()

                def on_progress(done: int) -> None:
                    job.done = done

                try:
                    job.result = await asyncio.wait_for(
                        runner(on_progress), self._timeout_seconds
                    )
                except asyncio.TimeoutError:
                    failure = AnalysisFailure(
                        ANALYSIS_TIMED_OUT,
                        f"The job did not finish within {self._timeout_seconds:g} seconds",
                    )
                    self._finish(job, "failed", error=failure.problem())
                    return
                except AnalysisFailure as failure:
                    self._finish(job, "failed", error=failure.problem())
                    return
                except Exception:
                    logger.exception("Analysis job %s failed", job.id)
                    failure = AnalysisFailure(
                        INTERNAL_ERROR, "The analysis failed unexpectedly"
                    )
                    self._finish(job, "failed", error=failure.problem())
                    return
                self._finish(job, "succeeded")
        except asyncio.CancelledError:
            if not job.finished:
                self._finish(job, "canceled")
            raise

    def _finish(
        self, job: Job, status: JobStatus, *, error: dict[str, Any] | None = None
    ) -> None:
        job.status = status
        job.error = error
        job.finished_at = _utcnow()
        job.finished_monotonic = self._clock()

    def _purge(self) -> None:
        now = self._clock()
        expired = [
            job
            for job in self._jobs.values()
            if job.finished_monotonic is not None
            and now - job.finished_monotonic >= self._retention_seconds
        ]
        for job in expired:
            self._forget(job)

    def _forget(self, job: Job) -> None:
        self._jobs.pop(job.id, None)
        if (
            job.idempotency_key is not None
            and self._by_key.get(job.idempotency_key) == job.id
        ):
            del self._by_key[job.idempotency_key]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
