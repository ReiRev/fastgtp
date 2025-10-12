"""FastAPI router wiring GTP transports to HTTP endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
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


class SessionResponse(BaseModel):
    """Response payload for session creation."""

    session_id: str


class QuitResponse(BaseModel):
    """Response payload for session termination."""

    closed: bool


class NameResponse(BaseModel):
    """Engine name reported by the GTP backend."""

    name: str


class VersionResponse(BaseModel):
    """Engine version reported by the GTP backend."""

    version: str


class ProtocolVersionResponse(BaseModel):
    """Protocol version supported by the GTP backend."""

    protocol_version: str


class FastGtp(APIRouter):
    """Router encapsulating REST endpoints backed by session-based GTP transports."""

    def __init__(self, **router_kwargs: Any) -> None:
        super().__init__(**router_kwargs)

        @self.post("/open")
        async def open_session(  # type: ignore[unused-coroutine]
            transport_manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> SessionResponse:
            """Create a new session backed by a dedicated transport."""
            session_id = await transport_manager.open_session()
            return SessionResponse(session_id=session_id)

        @self.get("/{session_id}/name")
        async def get_name(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> NameResponse:
            """Return the engine name according to the GTP."""
            payload = await self._query("name", transport)
            return NameResponse(name=payload)

        @self.get("/{session_id}/version")
        async def get_version(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> VersionResponse:
            """Return the engine version according to the GTP."""
            payload = await self._query("version", transport)
            return VersionResponse(version=payload)

        @self.get("/{session_id}/protocol_version")
        async def get_protocol_version(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> ProtocolVersionResponse:
            """Return the protocol version supported by the engine."""
            payload = await self._query("protocol_version", transport)
            return ProtocolVersionResponse(protocol_version=payload)

        @self.post("/{session_id}/quit")
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
    ) -> str:
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

        return structured.payload


def create_app(
    transport_manager: GTPTransportManager,
    *,
    app_kwargs: dict[str, Any] | None = None,
    router_kwargs: dict[str, Any] | None = None,
) -> FastAPI:
    """Create a FastAPI application that exposes the GTP router."""

    if app_kwargs is None:
        app_kwargs = {}
    if router_kwargs is None:
        router_kwargs = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await transport_manager.close_all()

    app = FastAPI(title="fastgtp", lifespan=lifespan, **app_kwargs)
    fastgtp_router = FastGtp(**router_kwargs)
    app.include_router(fastgtp_router)

    async def override_get_manager() -> GTPTransportManager:
        return transport_manager

    app.dependency_overrides[get_transport_manager] = override_get_manager

    return app
