"""Transport abstractions for communicating with GTP engines."""

from __future__ import annotations

import asyncio
import contextlib
import shlex
from asyncio.subprocess import PIPE, Process
from typing import Protocol, Sequence


class GTPTransport(Protocol):
    """Abstraction over something that can execute GTP commands."""

    async def send_command(self, command: str) -> str:
        """Send a single command and return the raw response."""


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

    async def aclose(self) -> None:
        """Terminate the managed subprocess if it is running."""
        if self._process is None:
            return
        if self._process.stdin is not None:
            self._process.stdin.close()
        if self._process.returncode is None:
            self._process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await self._process.wait()
        self._process = None

    async def _ensure_process(self) -> Process:
        if self._process is None or self._process.returncode is not None:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
            )
        return self._process

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
                    stderr_output = ""
                    if process.stderr is not None:
                        remaining = await process.stderr.read()
                        stderr_output = remaining.decode("utf-8", errors="replace")
                    raise RuntimeError(
                        "GTP engine terminated unexpectedly"
                        + (f": {stderr_output.strip()}" if stderr_output else "")
                    )

                decoded = line_bytes.decode("utf-8", errors="replace")
                lines.append(decoded)
                if decoded.strip() == "":
                    break

            return "".join(lines)


__all__ = ["GTPTransport", "SubprocessGTPTransport"]
