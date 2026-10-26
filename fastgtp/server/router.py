"""FastAPI router wiring GTP transports to HTTP endpoints.

The routes follow ``openapi.yaml``. Each GTP command is a change to a
resource (a session, its board or its moves), as ``docs/api-guidelines.md``
describes.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Sequence

from fastapi import APIRouter, Depends, FastAPI, Response
from pydantic import BaseModel

from .gtp import ParsedResponse, build_command, parse_response
from .problems import (
    ENGINE_ERROR,
    INTERNAL_ERROR,
    SESSION_NOT_FOUND,
    TOO_MANY_SESSIONS,
    ProblemError,
    install_problem_handlers,
)
from .transport import GTPTransport, GTPTransportManager, TooManySessionsError

logger = logging.getLogger(__name__)


async def get_transport_manager() -> GTPTransportManager:
    """Dependency placeholder overridden by the application."""
    raise ProblemError(
        INTERNAL_ERROR, "GTP transport manager dependency is not configured"
    )


@asynccontextmanager
async def _session(
    manager: GTPTransportManager, session_id: str
) -> AsyncIterator[GTPTransport]:
    try:
        transport, lock = await manager.get_session(session_id)
    except KeyError as exc:
        raise ProblemError(SESSION_NOT_FOUND, "Unknown session") from exc
    async with lock:
        # The session may have been deleted while this request waited.
        if not await manager.is_open(session_id, transport):
            raise ProblemError(SESSION_NOT_FOUND, "Unknown session")
        yield transport


class Engine(BaseModel):
    name: str
    version: str
    protocol_version: str
    commands: list[str]


class Session(BaseModel):
    session_id: str
    engine: Engine


class FastGtp(APIRouter):
    """Router encapsulating REST endpoints backed by session-based GTP transports."""

    def __init__(self, *, retry_after_seconds: int = 5, **router_kwargs: Any) -> None:
        super().__init__(**router_kwargs)

        @self.post("/sessions", status_code=201)
        async def create_session(  # type: ignore[unused-coroutine]
            response: Response,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Session:
            """Start an engine."""
            try:
                session_id = await manager.open_session()
            except TooManySessionsError as exc:
                raise ProblemError(
                    TOO_MANY_SESSIONS,
                    "fastgtp already runs as many sessions as it allows.",
                    headers={"Retry-After": str(retry_after_seconds)},
                ) from exc
            except Exception as exc:
                logger.warning("Could not start the engine: %s", exc)
                raise ProblemError(
                    ENGINE_ERROR, "The engine could not be started."
                ) from exc
            try:
                async with _session(manager, session_id) as transport:
                    engine = await self._engine(transport)
            except BaseException:
                # A session the client never learns about would never be deleted.
                await manager.close_session(session_id)
                raise
            response.headers["Location"] = f"/sessions/{session_id}"
            return Session(session_id=session_id, engine=engine)

        @self.get("/sessions/{session_id}")
        async def get_session(  # type: ignore[unused-coroutine]
            session_id: str,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Session:
            """Read a session."""
            async with _session(manager, session_id) as transport:
                engine = await self._engine(transport)
            return Session(session_id=session_id, engine=engine)

        @self.delete("/sessions/{session_id}", status_code=204)
        async def delete_session(  # type: ignore[unused-coroutine]
            session_id: str,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Response:
            """Stop an engine."""
            if not await manager.close_session(session_id):
                raise ProblemError(SESSION_NOT_FOUND, "Unknown session")
            return Response(status_code=204)

    async def _engine(self, transport: GTPTransport) -> Engine:
        commands = await self._query(transport, "list_commands")
        return Engine(
            name=await self._query(transport, "name"),
            version=await self._query(transport, "version"),
            protocol_version=await self._query(transport, "protocol_version"),
            commands=[line for line in commands.splitlines() if line],
        )

    async def _send(
        self,
        transport: GTPTransport,
        command: str,
        arguments: Sequence[str] | None = None,
    ) -> ParsedResponse:
        """Send a command and return the reply, success or failure."""
        try:
            raw = await transport.send_command(build_command(command, arguments))
        except Exception as exc:
            # The message can hold the engine's stderr, which must not reach
            # the client, so it is only logged.
            logger.warning("GTP command %r failed: %s", command, exc)
            raise ProblemError(
                ENGINE_ERROR, "The engine did not answer the command."
            ) from exc
        try:
            return parse_response(raw)
        except ValueError as exc:
            logger.warning("Unreadable reply to %r: %r", command, raw)
            raise ProblemError(
                ENGINE_ERROR, "The engine's reply could not be read."
            ) from exc

    async def _query(
        self,
        transport: GTPTransport,
        command: str,
        arguments: Sequence[str] | None = None,
    ) -> str:
        """Send a command that is expected to succeed and return its payload."""
        reply = await self._send(transport, command, arguments)
        if not reply.success:
            raise ProblemError(ENGINE_ERROR, reply.error or "Unknown GTP error")
        return reply.payload


def create_app(
    transport_manager: GTPTransportManager,
    *,
    retry_after_seconds: int = 5,
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
    install_problem_handlers(app)
    fastgtp_router = FastGtp(retry_after_seconds=retry_after_seconds, **router_kwargs)
    app.include_router(fastgtp_router)

    async def override_get_manager() -> GTPTransportManager:
        return transport_manager

    app.dependency_overrides[get_transport_manager] = override_get_manager

    return app
