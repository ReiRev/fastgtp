"""Transport abstractions and session management for GTP engines."""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import uuid
from asyncio.subprocess import PIPE, Process
from typing import Protocol, Sequence

_STDERR_CHUNK_BYTES = 4096
_STDERR_TAIL_BYTES = 8192
_TERMINATE_GRACE_SECONDS = 5.0
# KataGo prints every candidate move of an analysis on one line, which can
# pass asyncio's default line limit of 64 KiB.
_STDOUT_LINE_LIMIT_BYTES = 16 * 1024 * 1024


class GTPTransport(Protocol):
    """Abstraction over something that can execute GTP commands."""

    async def open(self) -> None:
        """Prepare the transport for use."""

    async def send_command(self, command: str) -> str:
        """Send a single command and return the raw response."""

    async def aclose(self) -> None:
        """Close the transport and release resources."""

    def copy(self) -> GTPTransport:
        """Return a new transport instance with the same configuration."""


class SubprocessGTPTransport(GTPTransport):
    """Execute GTP commands by interacting with an external engine process."""

    def __init__(self, command: Sequence[str] | str, *, respawn: bool = True):
        """Wrap the engine started by ``command``.

        With ``respawn`` set, a command sent after the engine has exited
        starts a new engine. Without it, the command fails, because a new
        engine has lost the board and settings the old one was given.
        """
        if isinstance(command, str):
            parsed = tuple(shlex.split(command))
        else:
            parsed = tuple(command)
        if not parsed:
            raise ValueError("GTP executable command cannot be empty")

        self._command: tuple[str, ...] = parsed
        self._respawn = respawn
        self._process: Process | None = None
        self._lock = asyncio.Lock()
        self._stderr_tail = bytearray()
        self._stderr_task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        """Spawn the subprocess if needed."""
        async with self._lock:
            await self._ensure_process()

    async def aclose(self) -> None:
        """Terminate the managed subprocess if it is running."""
        async with self._lock:
            if self._process is None:
                return
            process, self._process = self._process, None
            stderr_task, self._stderr_task = self._stderr_task, None
            shutdown = asyncio.ensure_future(_shut_down(process, stderr_task))
            _shutdowns.add(shutdown)
            shutdown.add_done_callback(_shutdowns.discard)
            # A second cancellation of the caller must not skip the SIGKILL
            # fallback, or an engine that ignores SIGTERM keeps running.
            await asyncio.shield(shutdown)

    async def _ensure_process(self) -> Process:
        if self._process is None or self._process.returncode is not None:
            if self._process is not None and not self._respawn:
                raise RuntimeError("GTP engine terminated unexpectedly")
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                limit=_STDOUT_LINE_LIMIT_BYTES,
            )
            if self._stderr_task is not None:
                self._stderr_task.cancel()
            self._stderr_tail.clear()
            # An engine that logs to stderr blocks once the pipe buffer fills,
            # so stderr is read for the whole life of the process.
            self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))
        return self._process

    async def _drain_stderr(self, process: Process) -> None:
        if process.stderr is None:
            return
        # Fixed-size reads keep memory bounded however long a line is.
        while chunk := await process.stderr.read(_STDERR_CHUNK_BYTES):
            self._stderr_tail += chunk
            del self._stderr_tail[:-_STDERR_TAIL_BYTES]

    async def send_command(self, command: str) -> str:
        async with self._lock:
            process = await self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("GTP engine streams are not available")

            stripped = command.strip()
            if not stripped:
                raise ValueError("GTP command cannot be empty")

            process.stdin.write((stripped + "\n").encode("utf-8"))
            await process.stdin.drain()

            lines: list[str] = []
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    if self._stderr_task is not None:
                        with contextlib.suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(
                                asyncio.shield(self._stderr_task),
                                _TERMINATE_GRACE_SECONDS,
                            )
                    stderr_output = self._stderr_tail.decode("utf-8", errors="replace")
                    raise RuntimeError(
                        "GTP engine terminated unexpectedly"
                        + (f": {stderr_output.strip()}" if stderr_output else "")
                    )

                decoded = line_bytes.decode("utf-8", errors="replace")
                lines.append(decoded)
                if decoded.strip() == "":
                    break

            return "".join(lines)

    def copy(self) -> SubprocessGTPTransport:
        """Create a fresh transport with the same command."""
        return SubprocessGTPTransport(self._command, respawn=self._respawn)


# Shutdowns that outlive a cancelled caller. The event loop keeps only weak
# references to tasks, so they are held here until they finish.
_shutdowns: set[asyncio.Future[None]] = set()


async def _shut_down(process: Process, stderr_task: asyncio.Task[None] | None) -> None:
    if process.stdin is not None:
        process.stdin.close()
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), _TERMINATE_GRACE_SECONDS)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if stderr_task is not None:
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task


class TooManySessionsError(Exception):
    """Raised when opening a session would pass the session limit."""


class GTPTransportManager:
    """Manage transport instances keyed by session identifiers."""

    def __init__(self, transport: GTPTransport, *, max_sessions: int | None = None):
        """Copy ``transport`` for each session, keeping at most ``max_sessions``."""
        self._transport = transport
        self._max_sessions = max_sessions
        self._sessions: dict[str, GTPTransport] = {}
        # One lock per session, so that a request that sends several commands
        # is not interleaved with another request to the same engine.
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._starting = 0
        self._closing = 0
        self._lock = asyncio.Lock()

    async def open_session(self) -> str:
        """Create and store a new transport, returning its session id."""
        async with self._lock:
            # Engines that are still starting or stopping count too, or a
            # burst of requests could run more engines than the limit.
            count = len(self._sessions) + self._starting + self._closing
            if self._max_sessions is not None and count >= self._max_sessions:
                raise TooManySessionsError()
            self._starting += 1
        try:
            transport = self._transport.copy()
            if asyncio.iscoroutine(transport):  # pragma: no cover - defensive
                transport = await transport  # type: ignore[assignment]
            await transport.open()
        finally:
            async with self._lock:
                self._starting -= 1

        session_id = uuid.uuid4().hex
        async with self._lock:
            while session_id in self._sessions:
                session_id = uuid.uuid4().hex
            self._sessions[session_id] = transport
            self._session_locks[session_id] = asyncio.Lock()
        return session_id

    async def get_session(self, session_id: str) -> tuple[GTPTransport, asyncio.Lock]:
        """Return the session's transport and the lock that serializes its requests."""
        async with self._lock:
            transport = self._sessions.get(session_id)
            lock = self._session_locks.get(session_id)
        if transport is None or lock is None:
            raise KeyError(session_id)
        return transport, lock

    async def close_session(self, session_id: str) -> bool:
        """Close and remove the transport for the given session."""
        transport: GTPTransport | None
        async with self._lock:
            transport = self._sessions.pop(session_id, None)
            lock = self._session_locks.pop(session_id, None)
            if transport is None or lock is None:
                return False
            self._closing += 1

        async def close_when_free() -> None:
            # Waiting for the session's lock lets a running request finish
            # first. Closing under it would leave that request to restart the
            # engine, with nothing tracking the new process.
            try:
                async with lock:
                    await transport.aclose()
            finally:
                async with self._lock:
                    self._closing -= 1

        # Shielded, so a cancelled caller does not leave the engine running
        # after the session is already gone from the table.
        closing = asyncio.ensure_future(close_when_free())
        _shutdowns.add(closing)
        closing.add_done_callback(_shutdowns.discard)
        await asyncio.shield(closing)
        return True

    async def is_open(self, session_id: str, transport: GTPTransport) -> bool:
        """Tell whether ``transport`` still belongs to an open session."""
        async with self._lock:
            return self._sessions.get(session_id) is transport

    async def close_all(self) -> None:
        """Close and clear all managed transports."""
        async with self._lock:
            transports = list(self._sessions.values())
            self._sessions.clear()
            self._session_locks.clear()
        results = await asyncio.gather(
            *(transport.aclose() for transport in transports),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                # Best-effort cleanup; surface in logs without interrupting shutdown.
                # Users can add logging here if desired.
                continue


__all__ = [
    "GTPTransport",
    "GTPTransportManager",
    "SubprocessGTPTransport",
    "TooManySessionsError",
]
