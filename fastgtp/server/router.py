"""FastAPI router wiring GTP transports to HTTP endpoints.

The routes follow ``openapi.yaml``. Each GTP command is a change to a
resource (a session, its board or its moves), as ``docs/api-guidelines.md``
describes.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Sequence

import yaml
from fastapi import APIRouter, Depends, FastAPI, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .gtp import ParsedResponse, build_command, parse_response
from .problems import (
    ENGINE_ERROR,
    ILLEGAL_MOVE,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    NO_MOVE_TO_UNDO,
    SESSION_NOT_FOUND,
    TOO_MANY_SESSIONS,
    ProblemError,
    install_problem_handlers,
)
from .transport import GTPTransport, GTPTransportManager, TooManySessionsError

logger = logging.getLogger(__name__)

# The spec at the root of the repository. It is the contract, so the app serves
# it as its OpenAPI document instead of the one FastAPI would generate.
SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"

Color = Literal["BLACK", "WHITE"]
_GTP_COLORS = {"BLACK": "B", "WHITE": "W"}
_GENERATED_VERTEX = re.compile(r"^([A-HJ-Z][1-9][0-9]?|PASS|RESIGN)$")
_SGF_SIZE = re.compile(r"\bSZ\[(\d+)")
# SGF's default when a record has no SZ property.
_DEFAULT_SIZE = 19


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


class Board(BaseModel):
    size: int
    komi: float
    sgf: str


class BoardInput(BaseModel):
    """Either an empty board (``size`` and ``komi``) or a position (``sgf``)."""

    model_config = ConfigDict(extra="forbid")

    size: int | None = Field(default=None, ge=2, le=25)
    komi: float | None = Field(default=None, allow_inf_nan=False)
    sgf: str | None = None
    move_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def one_kind(self) -> BoardInput:
        if self.sgf is not None:
            if self.size is not None or self.komi is not None:
                raise ValueError("send either size and komi, or sgf, not both")
        elif self.size is None or self.komi is None:
            raise ValueError("send size and komi, or sgf")
        elif self.move_count is not None:
            raise ValueError("move_count is only used with sgf")
        return self


class MoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    color: Color
    vertex: str | None = Field(default=None, pattern=r"^([A-HJ-Z][1-9][0-9]?|PASS)$")


class Move(BaseModel):
    color: Color
    vertex: str


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

        @self.get("/sessions/{session_id}/board")
        async def get_board(  # type: ignore[unused-coroutine]
            session_id: str,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Board:
            """Read the board."""
            async with _session(manager, session_id) as transport:
                return await self._board(transport)

        @self.put("/sessions/{session_id}/board")
        async def replace_board(  # type: ignore[unused-coroutine]
            session_id: str,
            request: BoardInput,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Board:
            """Replace the board."""
            async with _session(manager, session_id) as transport:
                if request.sgf is not None:
                    await self._load_sgf(transport, request.sgf, request.move_count)
                else:
                    reply = await self._send(
                        transport, "boardsize", [str(request.size)]
                    )
                    if not reply.success:
                        raise ProblemError(
                            INVALID_REQUEST,
                            reply.error or "The engine rejected the board size.",
                            field="size",
                        )
                    await self._query(transport, "clear_board")
                    reply = await self._send(transport, "komi", [str(request.komi)])
                    if not reply.success:
                        raise ProblemError(
                            INVALID_REQUEST,
                            reply.error or "The engine rejected the komi.",
                            field="komi",
                        )
                return await self._board(transport)

        @self.post("/sessions/{session_id}/moves", status_code=201)
        async def create_move(  # type: ignore[unused-coroutine]
            session_id: str,
            request: MoveInput,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Move:
            """Play or generate a move."""
            color = _GTP_COLORS[request.color]
            async with _session(manager, session_id) as transport:
                if request.vertex is None:
                    return await self._generate(transport, request.color)
                reply = await self._send(transport, "play", [color, request.vertex])
            if not reply.success:
                error = reply.error or "The engine rejected the move."
                # GTP says play fails with "illegal move" for a move the rules
                # forbid. Anything else, such as a point off the board, is an
                # invalid request.
                kind = (
                    ILLEGAL_MOVE
                    if error.lower().startswith("illegal move")
                    else INVALID_REQUEST
                )
                raise ProblemError(kind, error, field="vertex")
            return Move(color=request.color, vertex=request.vertex)

        @self.delete("/sessions/{session_id}/moves/last", status_code=204)
        async def delete_last_move(  # type: ignore[unused-coroutine]
            session_id: str,
            manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> Response:
            """Take back the last move."""
            async with _session(manager, session_id) as transport:
                reply = await self._send(transport, "undo")
            if not reply.success:
                raise ProblemError(
                    NO_MOVE_TO_UNDO, reply.error or "There is no move to take back."
                )
            return Response(status_code=204)

    async def _generate(self, transport: GTPTransport, color: str) -> Move:
        payload = await self._query(transport, "genmove", [_GTP_COLORS[color]])
        # Engines answer in either case, for example "pass" or "resign".
        vertex = payload.strip().upper()
        if not _GENERATED_VERTEX.match(vertex):
            raise ProblemError(ENGINE_ERROR, f"Invalid generated move: {payload!r}")
        return Move(color=color, vertex=vertex)

    async def _engine(self, transport: GTPTransport) -> Engine:
        commands = await self._query(transport, "list_commands")
        return Engine(
            name=await self._query(transport, "name"),
            version=await self._query(transport, "version"),
            protocol_version=await self._query(transport, "protocol_version"),
            commands=[line for line in commands.splitlines() if line],
        )

    async def _board(self, transport: GTPTransport) -> Board:
        sgf = await self._query(transport, "printsgf")
        komi = await self._query(transport, "get_komi")
        try:
            komi_value = float(komi)
        except ValueError as exc:
            raise ProblemError(ENGINE_ERROR, f"Invalid komi value: {komi!r}") from exc
        match = _SGF_SIZE.search(sgf)
        size = int(match.group(1)) if match else _DEFAULT_SIZE
        return Board(size=size, komi=komi_value, sgf=sgf)

    async def _load_sgf(
        self, transport: GTPTransport, sgf: str, move_count: int | None
    ) -> None:
        # GTP loadsgf reads a file, so the record goes through a temporary one.
        temp = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".sgf", delete=False
        )
        try:
            temp.write(sgf)
        finally:
            temp.close()
        filename = temp.name
        args = [filename]
        if move_count is not None:
            # loadsgf stops before the move it is given, so the first N moves
            # are loaded with N + 1.
            args.append(str(move_count + 1))
        try:
            reply = await self._send(transport, "loadsgf", args)
        finally:
            try:
                os.remove(filename)
            except OSError:
                pass
        if not reply.success:
            # Engines repeat the file name in their errors, and the server's
            # temporary path must not reach the client.
            error = reply.error or "The engine could not load the SGF."
            error = error.replace(f"'{filename}'", "the SGF")
            raise ProblemError(
                INVALID_REQUEST, error.replace(filename, "the SGF"), field="sgf"
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
    _serve_spec(app)
    install_problem_handlers(app)
    fastgtp_router = FastGtp(retry_after_seconds=retry_after_seconds, **router_kwargs)
    app.include_router(fastgtp_router)

    async def override_get_manager() -> GTPTransportManager:
        return transport_manager

    app.dependency_overrides[get_transport_manager] = override_get_manager

    return app


def _serve_spec(app: FastAPI) -> None:
    try:
        spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    except OSError:
        # An installed package does not include the spec. The generated
        # document is then served, which differs from the spec in its error
        # responses.
        logger.warning("%s not found; serving the generated OpenAPI", SPEC_PATH)
        return

    def openapi() -> dict[str, Any]:
        return spec

    app.openapi = openapi  # type: ignore[method-assign]
