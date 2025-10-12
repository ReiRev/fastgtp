"""FastAPI router wiring GTP transports to HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from .gtp import parse_response
from .transport import GTPTransport


class MetadataResponse(BaseModel):
    """REST response containing the parsed GTP payload."""

    data: str


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

        @self.get("/name")
        async def get_name() -> MetadataResponse:
            """Return the engine name according to the GTP."""
            return await self._query("name")

        @self.get("/version")
        async def get_version() -> MetadataResponse:
            """Return the engine version according to the GTP."""
            return await self._query("version")

        @self.get("/protocol_version")
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
    transport: GTPTransport,
    app_kwargs: dict[str, Any] = {},
    router_kwargs: dict[str, Any] = {},
) -> FastAPI:
    """Create a FastAPI application wired to the provided GTP model."""

    app = FastAPI(title="fastgtp", **router_kwargs)
    fastgtp_router = FastGtp(
        transport=transport,
        **router_kwargs,
    )

    app.include_router(fastgtp_router)
    return app
