"""FastAPI router wiring GTP transports to HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .gtp import parse_response
from .transport import GTPTransport, GTPTransportManager


async def get_transport_manager() -> GTPTransportManager:
    """Dependency placeholder overridden by the application."""
    raise HTTPException(
        status_code=500,
        detail="GTP transport manager dependency is not configured",
    )


async def get_session_transport(
    session_id: str,
    transport_manager: GTPTransportManager = Depends(get_transport_manager),
) -> GTPTransport:
    """Resolve the transport bound to the requested session."""
    try:
        return await transport_manager.get_transport(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown session") from exc


class MetadataResponse(BaseModel):
    """REST response containing the parsed GTP payload."""

    data: str


class SessionResponse(BaseModel):
    """Response payload for session creation."""

    session_id: str


class QuitResponse(BaseModel):
    """Response payload for session termination."""

    closed: bool


class FastGtp(APIRouter):
    """Router encapsulating REST endpoints backed by session-based GTP transports."""

    def __init__(self, **router_kwargs: Any) -> None:
        super().__init__(**router_kwargs)

        @self.post("/open", response_model=SessionResponse)
        async def open_session(  # type: ignore[unused-coroutine]
            transport_manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> SessionResponse:
            """Create a new session backed by a dedicated transport."""
            session_id = await transport_manager.open_session()
            return SessionResponse(session_id=session_id)

        @self.get("/{session_id}/name", response_model=MetadataResponse)
        async def get_name(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> MetadataResponse:
            """Return the engine name according to the GTP."""
            return await self._query("name", transport)

        @self.get("/{session_id}/version", response_model=MetadataResponse)
        async def get_version(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> MetadataResponse:
            """Return the engine version according to the GTP."""
            return await self._query("version", transport)

        @self.get("/{session_id}/protocol_version", response_model=MetadataResponse)
        async def get_protocol_version(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> MetadataResponse:
            """Return the protocol version supported by the engine."""
            return await self._query("protocol_version", transport)

        @self.post("/{session_id}/quit", response_model=QuitResponse)
        async def quit_session(  # type: ignore[unused-coroutine]
            session_id: str,
            transport_manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> QuitResponse:
            """Terminate the session and release its transport."""
            closed = await transport_manager.close_session(session_id)
            if not closed:
                raise HTTPException(status_code=404, detail="Unknown session")
            return QuitResponse(closed=True)

    async def _query(
        self,
        command: str,
        transport: GTPTransport,
    ) -> MetadataResponse:
        try:
            raw = await transport.send_command(command)
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
    app_kwargs: dict[str, Any] = {},
    router_kwargs: dict[str, Any] = {},
) -> FastAPI:
    """Create a FastAPI application that exposes the GTP router.

    The caller is responsible for configuring the `get_transport_manager`
    dependency via `app.dependency_overrides`.
    """

    app = FastAPI(title="fastgtp", **app_kwargs)
    fastgtp_router = FastGtp(**router_kwargs)
    app.include_router(fastgtp_router)
    return app
