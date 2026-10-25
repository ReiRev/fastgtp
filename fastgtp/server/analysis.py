"""Win rate analysis built from GTP commands.

Standard GTP commands set up the board and replay the game. KataGo's GTP
extensions (``kata-set-rules``, ``set_position``, ``rectangular_boardsize``
and ``kata-search_analyze``) set the rules, place setup stones and search a
position without playing a move. ``REQUIRED_COMMANDS`` lists them, so an
engine that lacks one is detected before any job runs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from .gtp import ParsedResponse, build_command, parse_response
from .problems import ENGINE_ERROR, ILLEGAL_MOVE, ProblemType
from .transport import GTPTransport

logger = logging.getLogger(__name__)

Color = Literal["B", "W"]
Rules = Literal[
    "japanese",
    "chinese",
    "korean",
    "aga",
    "tromp-taylor",
    "new-zealand",
    "stone-scoring",
]

REQUIRED_COMMANDS = frozenset(
    {
        "boardsize",
        "rectangular_boardsize",
        "clear_board",
        "komi",
        "play",
        "kata-set-rules",
        "set_position",
        "kata-search_analyze",
    }
)

# GTP skips the letter I in column names.
_COLUMNS = "ABCDEFGHJKLMNOPQRST"
_POINT_PATTERN = re.compile(r"^([A-HJ-T])([1-9][0-9]?)$")
_ROOT_WINRATE_PATTERN = re.compile(r"\brootInfo\b.*?\bwinrate\s+(\S+)")
_MAX_KOMI = 150.0
# Far above any real game. The cap bounds the work one job can ask for. The
# size of the request body itself is left to the reverse proxy in front.
MAX_MOVES = 1000
_MAX_SETUP_STONES = 19 * 19


class AnalysisFailure(Exception):
    """An analysis error that is reported to the client as a problem."""

    def __init__(
        self, kind: ProblemType, detail: str, field: str | None = None
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.field = field

    def problem(self) -> dict[str, Any]:
        """Return the failure as an RFC 9457 problem details object."""
        if self.field is None:
            return self.kind.body(self.detail)
        return self.kind.body(self.detail, field=self.field)


class Board(BaseModel):
    """Board dimensions."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=2, le=19)
    height: int = Field(ge=2, le=19)


class Stone(BaseModel):
    """A stone placed before the first move."""

    model_config = ConfigDict(extra="forbid")

    color: Color
    point: str = Field(max_length=8, description="GTP coordinate such as D4.")


class Move(BaseModel):
    """A move in the game record."""

    model_config = ConfigDict(extra="forbid")

    color: Color
    point: str = Field(max_length=8, description="GTP coordinate such as D4, or pass.")


class AnalysisRequest(BaseModel):
    """A game to analyze. Every position in it is analyzed."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    profile: str = Field(
        max_length=64, description="Name of the profile to analyze with."
    )
    board: Board
    rules: Rules
    komi: float
    setup: list[Stone] = Field(default_factory=list, max_length=_MAX_SETUP_STONES)
    initial_player: Color | None = Field(
        default=None,
        alias="initialPlayer",
        description="Side to play first. Defaults to W with setup stones, else B.",
    )
    moves: list[Move] = Field(max_length=MAX_MOVES)

    # Each check is a field validator, so its error is reported at that field.
    @field_validator("komi")
    @classmethod
    def _check_komi(cls, komi: float) -> float:
        if abs(komi) > _MAX_KOMI or not (komi * 2).is_integer():
            raise ValueError("komi must be a multiple of 0.5 between -150 and 150")
        return komi

    @field_validator("setup")
    @classmethod
    def _check_setup(cls, setup: list[Stone], info: ValidationInfo) -> list[Stone]:
        board = info.data.get("board")
        if board is None:
            return setup
        occupied: set[str] = set()
        for index, stone in enumerate(setup):
            stone.point = _normalize_point(
                stone.point, board, f"setup[{index}]", allow_pass=False
            )
            if stone.point in occupied:
                raise ValueError(f"setup[{index}]: {stone.point} is already taken")
            occupied.add(stone.point)
        return setup

    @field_validator("moves")
    @classmethod
    def _check_moves(cls, moves: list[Move], info: ValidationInfo) -> list[Move]:
        board = info.data.get("board")
        if board is None:
            return moves
        for index, move in enumerate(moves):
            move.point = _normalize_point(
                move.point, board, f"moves[{index}]", allow_pass=True
            )
        initial_player = info.data.get("initial_player")
        if initial_player is not None and moves and moves[0].color != initial_player:
            raise ValueError(
                f"initialPlayer is {initial_player}, "
                f"but moves[0] is played by {moves[0].color}"
            )
        return moves

    @property
    def turn_count(self) -> int:
        """Return the number of positions in the game, the empty one included."""
        return len(self.moves) + 1

    def player_at(self, turn: int) -> Color:
        """Return the side to play in the position after ``turn`` moves."""
        if turn < len(self.moves):
            return self.moves[turn].color
        if self.moves:
            return _opponent(self.moves[-1].color)
        if self.initial_player is not None:
            return self.initial_player
        return "W" if self.setup else "B"


@dataclass(frozen=True, slots=True)
class EngineInfo:
    """What an engine reported about itself at startup."""

    name: str
    version: str
    commands: frozenset[str]

    @property
    def missing_commands(self) -> frozenset[str]:
        """Return the required commands the engine does not support."""
        return REQUIRED_COMMANDS - self.commands


async def probe_engine(transport: GTPTransport) -> EngineInfo:
    """Ask a running engine for its name, version and command list."""
    name = await _send(transport, "name")
    version = await _send(transport, "version")
    commands = await _send(transport, "list_commands")
    return EngineInfo(
        name=name,
        version=version,
        commands=frozenset(line.strip() for line in commands.splitlines() if line),
    )


async def analyze_winrates(
    transport: GTPTransport,
    request: AnalysisRequest,
    on_progress: Callable[[int], None],
) -> list[dict[str, Any]]:
    """Replay the game and return Black's win rate after each move.

    Turn ``n`` is the position after ``n`` moves, so turn 0 is the position
    before the first move.
    """
    board = request.board
    if board.width == board.height:
        await _send(transport, "boardsize", [str(board.width)])
    else:
        await _send(
            transport, "rectangular_boardsize", [str(board.width), str(board.height)]
        )
    await _send(transport, "clear_board")
    await _send(transport, "kata-set-rules", [request.rules])
    await _send(transport, "komi", [_format_komi(request.komi)])
    if request.setup:
        stones = [
            part for stone in request.setup for part in (stone.color, stone.point)
        ]
        await _send(transport, "set_position", stones)

    results: list[dict[str, Any]] = []
    for turn in range(request.turn_count):
        winrate = await _search_winrate(transport, request.player_at(turn))
        results.append({"turn": turn, "blackWinrate": winrate})
        on_progress(len(results))
        if turn < len(request.moves):
            await _play(transport, turn, request.moves[turn])
    return results


async def _search_winrate(transport: GTPTransport, color: Color) -> float:
    # A large interval prints the analysis once, when the search finishes.
    payload = await _send(
        transport,
        "kata-search_analyze",
        [color, "interval", "100000", "rootInfo", "true"],
    )
    matches = _ROOT_WINRATE_PATTERN.findall(payload)
    if not matches:
        raise AnalysisFailure(
            ENGINE_ERROR, "kata-search_analyze returned no rootInfo winrate"
        )
    try:
        winrate = float(matches[-1])
    except ValueError as exc:
        raise AnalysisFailure(
            ENGINE_ERROR, f"Unreadable winrate {matches[-1]!r}"
        ) from exc
    if not 0.0 <= winrate <= 1.0:
        raise AnalysisFailure(ENGINE_ERROR, f"Winrate {winrate} is out of range")
    return winrate


async def _play(transport: GTPTransport, index: int, move: Move) -> None:
    raw = await _raw(transport, build_command("play", [move.color, move.point]))
    if not raw.success:
        raise AnalysisFailure(
            ILLEGAL_MOVE,
            f"moves[{index}]: {move.color} {move.point} is illegal",
            field=f"moves[{index}]",
        )


async def _send(
    transport: GTPTransport, name: str, arguments: Sequence[str] | None = None
) -> str:
    response = await _raw(transport, build_command(name, arguments))
    if not response.success:
        raise AnalysisFailure(
            ENGINE_ERROR, f"{name} failed: {response.error or 'unknown error'}"
        )
    return response.payload


async def _raw(transport: GTPTransport, command: str) -> ParsedResponse:
    try:
        raw = await transport.send_command(command)
        return parse_response(raw)
    except (RuntimeError, ValueError, ConnectionError) as exc:
        # The message can hold the engine's stderr, with file paths and other
        # details of the host, so clients get a fixed text and the log the rest.
        logger.warning("GTP engine failed on %r: %s", command, exc)
        raise AnalysisFailure(
            ENGINE_ERROR,
            "The engine stopped or sent a response that could not be read",
        ) from exc


def _normalize_point(value: str, board: Board, where: str, *, allow_pass: bool) -> str:
    point = value.strip().upper()
    if point == "PASS":
        if allow_pass:
            return "pass"
        raise ValueError(f"{where}: pass is not a board point")
    match = _POINT_PATTERN.fullmatch(point)
    if match is None:
        raise ValueError(f"{where}: {value!r} is not a GTP coordinate")
    column = _COLUMNS.index(match.group(1))
    row = int(match.group(2))
    if column >= board.width or row > board.height:
        raise ValueError(f"{where}: {point} is off the board")
    return point


def _format_komi(komi: float) -> str:
    return str(int(komi)) if komi.is_integer() else str(komi)


def _opponent(color: Color) -> Color:
    return "W" if color == "B" else "B"
