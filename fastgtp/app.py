"""FastAPI components for translating REST calls to GTP commands."""

from __future__ import annotations

import asyncio
import contextlib
import shlex
from asyncio.subprocess import PIPE, Process
from typing import Any, Protocol, Sequence

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from .gtp import parse_response


class GTPTransport(Protocol):
    """Abstraction over something that can execute GTP commands."""

    async def send_command(self, command: str) -> str:
        """Send a single command and return the raw response."""


class MetadataResponse(BaseModel):
    """REST response containing the parsed GTP payload."""

    data: str


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


class FastGtp(APIRouter):
    """Router encapsulating REST endpoints backed by a GTP transport."""

    def __init__(
        self,
        *,
        transport: GTPTransport | None = None,
        **router_kwargs: Any,
    ) -> None:
        if transport is None:
            raise ValueError("A transport must be provided")

        super().__init__(**router_kwargs)
        self._transport = transport

        @self.get("/name", response_model=MetadataResponse)
        async def get_name() -> MetadataResponse:
            """Return the engine name according to the GTP."""
            return await self._query("name")

        @self.get("/version", response_model=MetadataResponse)
        async def get_version() -> MetadataResponse:
            """Return the engine version according to the GTP."""
            return await self._query("version")

        @self.get("/protocol_version", response_model=MetadataResponse)
        async def get_protocol_version() -> MetadataResponse:
            """Return the protocol version supported by the engine."""
            return await self._query("protocol_version")

    async def _query(self, command: str) -> MetadataResponse:
        assert self._transport is not None  # For type checkers
        try:
            raw = await self._transport.send_command(command)
        except Exception as exc:  # pragma: no cover - transport specific
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        try:
            structured = parse_response(raw)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if not structured.success:
            raise HTTPException(
                status_code=502, detail=structured.error or "Unknown GTP error"
            )

        return MetadataResponse(data=structured.payload)


def create_app(
    transport: GTPTransport | None = None,
    router_kwargs: dict[str, Any] | None = None,
) -> FastAPI:
    """Create a FastAPI application wired to the provided GTP model."""

    app = FastAPI(title="fastgtp", version="0.1.0")

    kwargs = dict(router_kwargs or {})
    if transport is None:
        raise ValueError("A transport must be provided")
    fastgtp_router = FastGtp(
        transport=transport,
        **kwargs,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(fastgtp_router)
    return app
