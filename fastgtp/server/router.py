"""FastAPI router wiring GTP transports to HTTP endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .gtp import parse_response
from .transport import GTPTransport, GTPTransportManager, TransportFactory


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

    def __init__(
        self,
        *,
        transport_factory: TransportFactory | None = None,
        manager: GTPTransportManager | None = None,
        manager_dependency: (
            Callable[[], GTPTransportManager | Awaitable[GTPTransportManager]] | None
        ) = None,
        **router_kwargs: Any,
    ) -> None:
        if manager_dependency is None:
            if manager is None:
                if transport_factory is None:
                    raise ValueError(
                        "A transport factory or manager dependency must be provided"
                    )
                manager = GTPTransportManager(transport_factory)
            manager_dependency = lambda: manager

        super().__init__(**router_kwargs)
        self._manager_dependency = manager_dependency

        async def session_transport_dependency(
            session_id: str,
            session_manager: GTPTransportManager = Depends(self._manager_dependency),
        ) -> GTPTransport:
            try:
                return await session_manager.get_transport(session_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Unknown session") from exc

        self._transport_dependency = session_transport_dependency

        @self.post("/open", response_model=SessionResponse)
        async def open_session(
            session_manager: GTPTransportManager = Depends(self._manager_dependency),
        ) -> SessionResponse:
            """Create a new session backed by a dedicated transport."""
            session_id = await session_manager.open_session()
            return SessionResponse(session_id=session_id)

        @self.get(
            "/{session_id}/name",
            response_model=MetadataResponse,
        )
        async def get_name(
            transport: GTPTransport = Depends(self._transport_dependency),
        ) -> MetadataResponse:
            """Return the engine name according to the GTP."""
            return await self._query("name", transport)

        @self.get(
            "/{session_id}/version",
            response_model=MetadataResponse,
        )
        async def get_version(
            transport: GTPTransport = Depends(self._transport_dependency),
        ) -> MetadataResponse:
            """Return the engine version according to the GTP."""
            return await self._query("version", transport)

        @self.get(
            "/{session_id}/protocol_version",
            response_model=MetadataResponse,
        )
        async def get_protocol_version(
            transport: GTPTransport = Depends(self._transport_dependency),
        ) -> MetadataResponse:
            """Return the protocol version supported by the engine."""
            return await self._query("protocol_version", transport)

        @self.post(
            "/{session_id}/quit",
            response_model=QuitResponse,
        )
        async def quit_session(
            session_id: str,
            session_manager: GTPTransportManager = Depends(self._manager_dependency),
        ) -> QuitResponse:
            """Terminate the session and release its transport."""
            closed = await session_manager.close_session(session_id)
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
    transport_factory: TransportFactory,
    app_kwargs: dict[str, Any] | None = None,
    router_kwargs: dict[str, Any] | None = None,
) -> FastAPI:
    """Create a FastAPI application wired to session-based GTP transports."""

    if app_kwargs is None:
        app_kwargs = {}
    if router_kwargs is None:
        router_kwargs = {}

    app = FastAPI(title="fastgtp", **app_kwargs)
    manager = GTPTransportManager(transport_factory)
    fastgtp_router = FastGtp(
        manager=manager,
        **router_kwargs,
    )

    app.include_router(fastgtp_router)

    @app.on_event("shutdown")
    async def _close_sessions() -> None:
        await manager.close_all()

    return app
