"""FastAPI router wiring GTP transports to HTTP endpoints."""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Literal, Sequence

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from .gtp import build_command, parse_response
from .transport import GTPTransport, GTPTransportManager

ColorType = Literal["B", "W"]


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


class OpenSessionResponse(BaseModel):
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


class CommandsResponse(BaseModel):
    """Command list supported by the GTP backend."""

    commands: list[str]


class BoardSizeRequest(BaseModel):
    """Request payload for configuring the board size."""

    x: int
    y: int | None = None


class BoardSizeResponse(BaseModel):
    """Response payload for board size updates."""

    detail: str


class KomiRequest(BaseModel):
    """Request payload for configuring komi."""

    value: float


class KomiResponse(BaseModel):
    """Response payload for komi updates."""

    detail: str


class KomiValueResponse(BaseModel):
    """Current komi configured on the board."""

    komi: float


class PlayRequest(BaseModel):
    """Request payload for play commands."""

    color: ColorType
    vertex: str = Field(
        ...,
        description="Board coordinate in letter+number format (e.g. E12).",
        examples=["D4", "K10"],
    )

    @field_validator("vertex")
    @classmethod
    def validate_vertex(cls, value: str) -> str:
        if not value:
            raise ValueError("vertex cannot be empty")
        if not re.fullmatch(r"[A-Za-z]\d+", value):
            raise ValueError("vertex must be letter+digits (e.g. E12)")
        return value.upper()


class PlayResponse(BaseModel):
    """Response payload for play commands."""

    detail: str


class ClearBoardResponse(BaseModel):
    """Response payload for clearing the board."""

    detail: str


class GenMoveRequest(BaseModel):
    """Request payload for generating a move."""

    color: ColorType


class GenMoveResponse(BaseModel):
    """Response payload for generated moves."""

    move: str


class SgfResponse(BaseModel):
    """Response payload for SGF exports."""

    sgf: str


class LoadSgfRequest(BaseModel):
    """Request payload for loading an SGF file."""

    content: str = Field(
        ...,
        description="SGF contents to load into the engine.",
    )
    move: int | None = Field(
        default=None,
        description="Optional move number to stop loading at.",
        strict=True,
    )


class LoadSgfResponse(BaseModel):
    """Response payload for SGF loading."""

    detail: str


class CommandRequest(BaseModel):
    """Command Request"""

    command: str


class CommandResponse(BaseModel):
    """Command Response"""

    detail: str


class FastGtp(APIRouter):
    """Router encapsulating REST endpoints backed by session-based GTP transports."""

    def __init__(self, **router_kwargs: Any) -> None:
        super().__init__(**router_kwargs)

        @self.post("/open_session", status_code=201)
        async def open_session(  # type: ignore[unused-coroutine]
            transport_manager: GTPTransportManager = Depends(get_transport_manager),
        ) -> OpenSessionResponse:
            """Create a new session backed by a dedicated transport."""
            session_id = await transport_manager.open_session()
            return OpenSessionResponse(session_id=session_id)

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

        @self.get("/{session_id}/commands")
        async def list_commands(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> CommandsResponse:
            """Return the list of commands supported by the engine."""
            payload = await self._query("list_commands", transport)
            commands = [line for line in payload.splitlines() if line]
            return CommandsResponse(commands=commands)

        @self.post("/{session_id}/boardsize")
        async def set_boardsize(  # type: ignore[unused-coroutine]
            request: BoardSizeRequest,
            transport: GTPTransport = Depends(get_session_transport),
        ) -> BoardSizeResponse:
            """Set the board size to NxN or NxM and clear the board."""
            args: list[str] = [str(request.x)]
            if request.y is not None:
                args.append(str(request.y))
            payload = await self._query("boardsize", transport, arguments=args)
            return BoardSizeResponse(detail=payload)

        @self.post("/{session_id}/komi")
        async def set_komi(  # type: ignore[unused-coroutine]
            request: KomiRequest,
            transport: GTPTransport = Depends(get_session_transport),
        ) -> KomiResponse:
            """Set the komi value on the board."""
            payload = await self._query(
                "komi", transport, arguments=[str(request.value)]
            )
            return KomiResponse(detail=payload)

        @self.get("/{session_id}/komi")
        async def get_komi(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> KomiValueResponse:
            """Return the current komi reported by the engine."""
            payload = await self._query("get_komi", transport)
            try:
                komi = float(payload)
            except ValueError as exc:
                raise HTTPException(
                    status_code=502, detail=f"Invalid komi value: {payload!r}"
                ) from exc
            return KomiValueResponse(komi=komi)

        @self.post("/{session_id}/play")
        async def play_move(  # type: ignore[unused-coroutine]
            request: PlayRequest,
            transport: GTPTransport = Depends(get_session_transport),
        ) -> PlayResponse:
            """Play a move on the board for the given color."""
            payload = await self._query(
                "play",
                transport,
                arguments=[request.color, request.vertex],
            )
            return PlayResponse(detail=payload)

        @self.post("/{session_id}/clear_board")
        async def clear_board(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> ClearBoardResponse:
            """Clear the current board state."""
            payload = await self._query("clear_board", transport)
            return ClearBoardResponse(detail=payload)

        @self.post("/{session_id}/genmove")
        async def genmove(  # type: ignore[unused-coroutine]
            request: GenMoveRequest,
            transport: GTPTransport = Depends(get_session_transport),
        ) -> GenMoveResponse:
            """Generate and play the next move for the given color."""
            payload = await self._query("genmove", transport, arguments=[request.color])
            return GenMoveResponse(move=payload)

        @self.get("/{session_id}/sgf")
        async def get_sgf(  # type: ignore[unused-coroutine]
            transport: GTPTransport = Depends(get_session_transport),
        ) -> SgfResponse:
            """Return the current position encoded as SGF."""
            payload = await self._query("printsgf", transport)
            return SgfResponse(sgf=payload)

        @self.post("/{session_id}/sgf")
        async def load_sgf(  # type: ignore[unused-coroutine]
            request: LoadSgfRequest,
            transport: GTPTransport = Depends(get_session_transport),
        ) -> LoadSgfResponse:
            """loadsgf: Load an SGF file, possibly up to a move number or the first occurrence of a move.

            Arguments: filename + move number, vertex, or nothing
            Fails:     missing filename or failure to open or parse file
            Returns:   color to play
            """
            temp = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".sgf", delete=False
            )
            try:
                temp.write(request.content)
                temp.flush()
            finally:
                temp.close()

            filename = temp.name
            args = [filename]
            if request.move is not None:
                args.append(str(request.move))
            try:
                payload = await self._query("loadsgf", transport, arguments=args)
                return LoadSgfResponse(detail=payload)
            finally:
                try:
                    os.remove(filename)
                except OSError:
                    pass

        @self.post("/{session_id}/command")
        async def send_command(  # type: ignore[unused-coroutine]
            request: CommandRequest,
            transport: GTPTransport = Depends(get_session_transport),
        ) -> CommandResponse:
            """Forward arbitrary commands to the underlying GTP engine."""
            payload = await self._query(request.command, transport)
            return CommandResponse(detail=payload)

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
        *,
        arguments: Sequence[str] | None = None,
    ) -> str:
        try:
            command_text = build_command(command, arguments)
            raw = await transport.send_command(command_text)
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
