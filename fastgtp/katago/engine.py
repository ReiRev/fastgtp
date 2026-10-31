"""One ``katago analysis`` process, shared by every query sent to it.

KataGo's analysis engine reads one JSON query per line and answers each
analyzed turn with one JSON line, in any order. Lines carry the query's ``id``,
so one task reads stdout and hands each line to the query it belongs to.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from asyncio.subprocess import PIPE, Process
from pathlib import PurePath
from typing import Any, Mapping, Sequence

from fastgtp.server.transport import _STDOUT_LINE_LIMIT_BYTES, _shut_down

logger = logging.getLogger(__name__)

_STDERR_CHUNK_BYTES = 4096
_STDERR_TAIL_BYTES = 8192
_STDERR_WAIT_SECONDS = 1.0

# fastgtp's spec reports every value from Black's point of view, whatever the
# config file says.
REQUIRED_OVERRIDES = {"reportAnalysisWinratesAs": "BLACK"}

STOPPED_ERROR = {"error": "KataGo stopped before the query finished."}


class KataGoError(Exception):
    """KataGo answered an action with an error, or stopped before answering."""


class RunningQuery:
    """What KataGo has sent so far for one query."""

    def __init__(self, katago_id: str, turns: int) -> None:
        self.katago_id = katago_id
        self.responses: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None
        self.done = asyncio.Event()
        self._turns_left = turns

    def _receive(self, message: dict[str, Any]) -> None:
        if "error" in message:
            # KataGo checks the whole query before it analyzes any turn, so
            # nothing follows an error.
            self.error = message
            self.done.set()
        elif "warning" in message:
            self.warnings.append(message)
        elif not message.get("isDuringSearch", False):
            # A terminated turn that KataGo had not started still ends with a
            # final line, marked noResults. It counts as finished but has no
            # analysis to keep.
            if not message.get("noResults", False):
                self.responses.append(message)
            self._turns_left -= 1
            if self._turns_left <= 0:
                self.done.set()

    def _fail(self, error: dict[str, Any]) -> None:
        if not self.done.is_set():
            self.error = error
            self.done.set()


class KataGoEngine:
    """Run ``katago analysis`` and route its output to queries."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        configs: Sequence[str],
        model: str,
        human_model: str | None = None,
        overrides: Mapping[str, str] | None = None,
    ) -> None:
        """Start KataGo as ``command analysis -config ... -model ...``.

        ``command`` is the executable, with any arguments that come before the
        ``analysis`` subcommand. ``overrides`` are passed with
        ``-override-config``, and fastgtp's required settings replace any
        with the same name.
        """
        if not command:
            raise ValueError("KataGo command cannot be empty")
        if not configs:
            raise ValueError("KataGo needs at least one config file")
        merged = {**(overrides or {}), **REQUIRED_OVERRIDES}
        for key, value in merged.items():
            # KataGo splits -override-config on commas and "=".
            if any(c in f"{key}{value}" for c in ",=\n"):
                raise ValueError(f"Cannot pass the override {key!r} to KataGo")

        args = [*command, "analysis"]
        for config in configs:
            args += ["-config", config]
        args += ["-model", model]
        if human_model is not None:
            args += ["-human-model", human_model]
        args += ["-override-config", ",".join(f"{k}={v}" for k, v in merged.items())]
        self._args: tuple[str, ...] = tuple(args)

        self.version: dict[str, Any] = {}
        self.models: list[dict[str, Any]] = []
        self._process: Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[bytes] | None = None
        self._queries: dict[str, RunningQuery] = {}
        self._actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start KataGo and read its version and models."""
        async with self._lock:
            await self._ensure_process()
        version = await self._action("query_version")
        self.version = {"version": version["version"], "git_hash": version["git_hash"]}
        models = (await self._action("query_models"))["models"]
        # KataGo reports the model path as configured, which would show where
        # the server keeps its files.
        self.models = [{**m, "name": PurePath(m["name"]).name} for m in models]

    async def submit(self, query: Mapping[str, Any]) -> RunningQuery:
        """Send ``query`` to KataGo. Its ``id`` is replaced with fastgtp's own.

        A KataGo that has stopped is started again first.
        """
        if "action" in query:
            # KataGo would treat the line as that action, not as a query.
            raise ValueError("A query cannot have an action")
        turns = len(set(query.get("analyzeTurns", [None])))
        if turns == 0:
            # KataGo answers an empty analyzeTurns with nothing at all, so
            # the query would never finish.
            raise ValueError("analyzeTurns cannot be empty")
        running = RunningQuery(uuid.uuid4().hex, turns)
        # Encoded first, so a query that cannot be sent is never registered.
        line = _encode({**query, "id": running.katago_id})
        async with self._lock:
            await self._ensure_process()
            self._queries[running.katago_id] = running
            await self._write(line)
        return running

    async def terminate(self, running: RunningQuery) -> None:
        """Ask KataGo to stop ``running``. It is done once KataGo has stopped."""
        if not running.done.is_set():
            await self._action("terminate", terminateId=running.katago_id)

    async def aclose(self) -> None:
        """Stop KataGo. Queries that have not finished fail."""
        async with self._lock:
            process, self._process = self._process, None
            if process is None:
                return
            await _shut_down(process, self._stderr_task)
            if self._reader is not None:
                await self._reader

    async def _action(self, action: str, **fields: Any) -> dict[str, Any]:
        action_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            if self._process is None or self._process.returncode is not None:
                raise KataGoError("KataGo is not running")
            self._actions[action_id] = future
            await self._write(_encode({"id": action_id, "action": action, **fields}))
        return await future

    async def _ensure_process(self) -> Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        if self._reader is not None:
            # The old reader fails the old process's queries; let it finish so
            # it does not fail queries sent to the new one.
            await self._reader
        self._process = await asyncio.create_subprocess_exec(
            *self._args,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            limit=_STDOUT_LINE_LIMIT_BYTES,
        )
        # KataGo logs to stderr, and blocks once the pipe buffer fills.
        self._stderr_task = asyncio.create_task(_drain(self._process))
        self._reader = asyncio.create_task(self._read(self._process, self._stderr_task))
        return self._process

    async def _write(self, line: bytes) -> None:
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(line)
        try:
            await self._process.stdin.drain()
        except ConnectionResetError:
            # The reader sees the same exit and fails what is waiting.
            pass

    async def _read(self, process: Process, stderr_task: asyncio.Task[bytes]) -> None:
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("KataGo wrote a line that is not JSON")
                    continue
                self._route(message)
        except Exception:
            # Without this task nothing would ever finish, so KataGo is
            # stopped and the queries fail below. The next query restarts it.
            logger.exception("Could not read KataGo's output")
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.wait()
        # aclose clears _process first, so only an exit nobody asked for is
        # logged.
        if self._process is process:
            # stderr can close a little after the process exits.
            await asyncio.wait({stderr_task}, timeout=_STDERR_WAIT_SECONDS)
            stderr_tail = b""
            if stderr_task.done() and not stderr_task.cancelled():
                stderr_tail = stderr_task.result()
            logger.warning(
                "KataGo exited with code %s: %s",
                process.returncode,
                stderr_tail.decode("utf-8", errors="replace").strip(),
            )
        for running in self._queries.values():
            running._fail(STOPPED_ERROR)
        self._queries.clear()
        for future in self._actions.values():
            if not future.done():
                future.set_exception(KataGoError("KataGo stopped"))
        self._actions.clear()

    def _route(self, message: Any) -> None:
        message_id = message.get("id") if isinstance(message, dict) else None
        if message_id in self._actions:
            future = self._actions.pop(message_id)
            if future.done():
                # The caller was cancelled and no longer waits.
                pass
            elif "error" in message:
                future.set_exception(KataGoError(message["error"]))
            else:
                future.set_result(message)
        elif message_id in self._queries:
            running = self._queries[message_id]
            running._receive(message)
            if running.done.is_set():
                del self._queries[message_id]
        else:
            # An error about a line KataGo could not read has no id. fastgtp
            # writes every line itself, so this is a bug worth logging.
            logger.warning("KataGo sent a message for no known query: %s", message)


def _encode(message: dict[str, Any]) -> bytes:
    # KataGo cannot read NaN or Infinity, and would report the line without
    # an id, so the query would never finish.
    return (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")


async def _drain(process: Process) -> bytes:
    """Read stderr until it closes, and return its end for the log."""
    assert process.stderr is not None
    tail = bytearray()
    while chunk := await process.stderr.read(_STDERR_CHUNK_BYTES):
        tail += chunk
        del tail[:-_STDERR_TAIL_BYTES]
    return bytes(tail)
