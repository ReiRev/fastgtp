"""Queries kept in memory, and the order KataGo runs them in."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastgtp.katago.engine import KataGoEngine, KataGoError, RunningQuery

logger = logging.getLogger(__name__)

TIMED_OUT_ERROR = {"error": "The query ran longer than the server allows."}
NOT_STARTED_ERROR = {"error": "KataGo could not be started."}
# How long a terminated query may take to send its last lines.
_TERMINATE_WAIT_SECONDS = 30.0


class QueueFullError(Exception):
    """Raised when a query would wait behind more queries than allowed."""


class Query:
    """One query and what KataGo has sent for it."""

    def __init__(self, query: dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex
        self.query = query
        self.status = "QUEUED"
        self.created_at = _now()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.running: RunningQuery | None = None
        self.error: dict[str, Any] | None = None
        self.deleted = False
        self.task: asyncio.Task[None] | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("SUCCEEDED", "FAILED")

    def to_json(self) -> dict[str, Any]:
        running = self.running
        responses = sorted(running.responses if running else [], key=_turn)
        body: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "query": self.query,
            # KataGo's lines carry the engine's id, not this query's.
            "responses": [{**r, "id": self.id} for r in responses],
            "warnings": [_without_id(w) for w in (running.warnings if running else [])],
            "createdAt": self.created_at,
        }
        if self.error is not None:
            body["error"] = _without_id(self.error)
        if self.started_at is not None:
            body["startedAt"] = self.started_at
        if self.finished_at is not None:
            body["finishedAt"] = self.finished_at
        return body


class KataGoQueries:
    """The queries of one KataGo, run a few at a time in the order they came."""

    def __init__(
        self,
        engine: KataGoEngine,
        *,
        max_running: int = 1,
        max_queued: int = 64,
        timeout_seconds: float = 600.0,
        keep_seconds: float = 600.0,
        max_visits: int | None = None,
    ) -> None:
        self.engine = engine
        self.max_visits = max_visits
        self._max_queued = max_queued
        self._timeout = timeout_seconds
        self._keep = keep_seconds
        self._slots = asyncio.Semaphore(max_running)
        self._queries: dict[str, Query] = {}

    def create(self, query: dict[str, Any]) -> Query:
        """Queue ``query`` and return it."""
        queued = sum(q.status == "QUEUED" for q in self._queries.values())
        if queued >= self._max_queued:
            raise QueueFullError()
        item = Query(query)
        self._queries[item.id] = item
        item.task = asyncio.create_task(self._run(item))
        return item

    def get(self, query_id: str) -> Query | None:
        return self._queries.get(query_id)

    async def delete(self, query_id: str) -> bool:
        """Remove a query, stopping it first. False if there is none."""
        item = self._queries.pop(query_id, None)
        if item is None:
            return False
        item.deleted = True
        if item.status == "QUEUED" and item.task is not None:
            # Still waiting for a slot, so KataGo has not seen it.
            item.task.cancel()
        elif item.running is not None and not item.running.done.is_set():
            await self._terminate(item.running)
        # A query between "RUNNING" and the end of submit is stopped by
        # _run, which checks `deleted` once submit returns.
        return True

    async def aclose(self) -> None:
        """Cancel every query's task. The engine is closed by its owner."""
        for item in self._queries.values():
            if item.task is not None:
                item.task.cancel()
        self._queries.clear()

    async def _run(self, item: Query) -> None:
        async with self._slots:
            item.status = "RUNNING"
            item.started_at = _now()
            try:
                item.running = await self.engine.submit(item.query)
            except ValueError as exc:
                # The routes check queries first, so this is a missed case.
                self._finish(item, {"error": str(exc)})
                return
            except (KataGoError, OSError) as exc:
                logger.warning("Could not send a query to KataGo: %s", exc)
                self._finish(item, NOT_STARTED_ERROR)
                return
            if item.deleted:
                await self._terminate(item.running)
                return
            try:
                await asyncio.wait_for(item.running.done.wait(), self._timeout)
            except asyncio.TimeoutError:
                await self._terminate(item.running)
                self._finish(item, TIMED_OUT_ERROR)
                return
            self._finish(item, item.running.error)

    def _finish(self, item: Query, error: dict[str, Any] | None) -> None:
        item.error = error
        item.status = "FAILED" if error is not None else "SUCCEEDED"
        item.finished_at = _now()
        if not item.deleted:
            asyncio.get_running_loop().call_later(
                self._keep, self._queries.pop, item.id, None
            )

    async def _terminate(self, running: RunningQuery) -> None:
        # The query keeps its slot until KataGo has really stopped it, so the
        # next query does not run beside it.
        with contextlib.suppress(KataGoError):
            await self.engine.terminate(running)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(running.done.wait(), _TERMINATE_WAIT_SECONDS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")[:-6] + "Z"


def _turn(response: dict[str, Any]) -> int:
    return response.get("turnNumber", 0)


def _without_id(message: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in message.items() if k != "id"}
