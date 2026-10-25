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

    def __init__(self, command: Sequence[str] | str):
        if isinstance(command, str):
            parsed = tuple(shlex.split(command))
        else:
            parsed = tuple(command)
        if not parsed:
            raise ValueError("GTP executable command cannot be empty")

        self._command: tuple[str, ...] = parsed
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
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
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
        # Fixed-size reads, because readline() stops at a line over 64 KiB.
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
                        with contextlib.suppress(
                            asyncio.CancelledError, asyncio.TimeoutError
                        ):
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
        return SubprocessGTPTransport(self._command)


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


class GTPTransportManager:
    """Manage transport instances keyed by session identifiers."""

    def __init__(self, transport: GTPTransport):
        self._transport = transport
        self._sessions: dict[str, GTPTransport] = {}
        self._lock = asyncio.Lock()

    async def open_session(self) -> str:
        """Create and store a new transport, returning its session id."""
        transport = self._transport.copy()
        if asyncio.iscoroutine(transport):  # pragma: no cover - defensive
            transport = await transport  # type: ignore[assignment]
        await transport.open()

        session_id = uuid.uuid4().hex
        async with self._lock:
            while session_id in self._sessions:
                session_id = uuid.uuid4().hex
            self._sessions[session_id] = transport
        return session_id

    async def get_transport(self, session_id: str) -> GTPTransport:
        """Retrieve a transport for the given session id."""
        async with self._lock:
            transport = self._sessions.get(session_id)
        if transport is None:
            raise KeyError(session_id)
        return transport

    async def close_session(self, session_id: str) -> bool:
        """Close and remove the transport for the given session."""
        transport: GTPTransport | None
        async with self._lock:
            transport = self._sessions.pop(session_id, None)
        if transport is None:
            return False
        await transport.aclose()
        return True

    async def close_all(self) -> None:
        """Close and clear all managed transports."""
        async with self._lock:
            transports = list(self._sessions.values())
            self._sessions.clear()
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
]
