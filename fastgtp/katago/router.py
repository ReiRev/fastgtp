"""The routes of the KataGo extension, as ``fastgtp/katago/openapi.yaml`` describes."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Any, Literal, Mapping

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt

from fastgtp.katago.config import KataGoSettings
from fastgtp.katago.engine import KataGoEngine
from fastgtp.katago.queries import KataGoQueries, QueueFullError
from fastgtp.server.problems import (
    INVALID_REQUEST,
    KATAGO_NOT_FOUND,
    QUERY_NOT_FOUND,
    QUEUE_FULL,
    ProblemError,
)

SPEC = files("fastgtp") / "katago" / "openapi.yaml"

Player = Literal["B", "W", "b", "w"]
KataGoMove = tuple[Player, str]


class KataGoQueryInput(BaseModel):
    # The field names are KataGo's, so the extension keeps them in camelCase.
    # Numbers and booleans are strict, so that "19" or true is not turned
    # into a value the client did not send.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    moves: list[KataGoMove] = Field(max_length=1000)
    initialStones: list[KataGoMove] | None = Field(None, max_length=361)
    initialPlayer: Player | None = None
    rules: str | dict[str, Any]
    komi: StrictFloat | None = None
    whiteHandicapBonus: Literal["0", "N", "N-1"] | None = None
    boardXSize: StrictInt
    boardYSize: StrictInt
    analyzeTurns: list[StrictInt] | None = Field(None, min_length=1, max_length=1001)
    maxVisits: StrictInt | None = None
    rootPolicyTemperature: StrictFloat | None = None
    rootFpuReductionMax: StrictFloat | None = None
    analysisPVLen: StrictInt | None = None
    includeOwnership: StrictBool | None = None
    includeOwnershipStdev: StrictBool | None = None
    includeMovesOwnership: StrictBool | None = None
    includeMovesOwnershipStdev: StrictBool | None = None
    includePolicy: StrictBool | None = None
    includePVVisits: StrictBool | None = None
    includeNoResultValue: StrictBool | None = None
    avoidMoves: list[dict[str, Any]] | None = None
    allowMoves: list[dict[str, Any]] | None = None
    focusMoves: list[str] | None = None
    focusWeights: list[StrictFloat] | None = None
    focusProb: StrictFloat | None = None


class KataGoRouter(APIRouter):
    """Routes for each KataGo in ``katagos``, keyed by the name in the path."""

    def __init__(
        self,
        katagos: Mapping[str, KataGoQueries],
        *,
        poll_after_seconds: int = 1,
        retry_after_seconds: int = 5,
        **router_kwargs: Any,
    ) -> None:
        super().__init__(**router_kwargs)

        def katago(katago_id: str) -> KataGoQueries:
            if katago_id not in katagos:
                raise ProblemError(KATAGO_NOT_FOUND, "Unknown KataGo")
            return katagos[katago_id]

        def query_response(item, status_code: int = 200, **headers: str):
            if not item.finished:
                headers["Retry-After"] = str(poll_after_seconds)
            return JSONResponse(
                item.to_json(), status_code=status_code, headers=headers
            )

        @self.get("/katago")
        async def list_katagos() -> dict[str, Any]:
            return {"items": [{"id": name} for name in katagos]}

        @self.get("/katago/{katago_id}/version")
        async def get_version(katago_id: str) -> dict[str, Any]:
            return katago(katago_id).engine.version

        @self.get("/katago/{katago_id}/models")
        async def get_models(katago_id: str) -> dict[str, Any]:
            return {"models": katago(katago_id).engine.models}

        @self.post("/katago/{katago_id}/queries", status_code=201)
        async def create_query(katago_id: str, body: KataGoQueryInput):
            queries = katago(katago_id)
            # A field set to null means the same as a missing one, and KataGo
            # would reject null.
            query = body.model_dump(exclude_none=True)
            if queries.max_visits is not None and body.maxVisits is not None:
                if body.maxVisits > queries.max_visits:
                    raise ProblemError(
                        INVALID_REQUEST,
                        f"maxVisits may not be larger than {queries.max_visits}.",
                        field="maxVisits",
                    )
            try:
                # Objects such as rules are not checked field by field, and
                # KataGo cannot read NaN or Infinity inside them either.
                json.dumps(query, allow_nan=False)
            except ValueError as exc:
                raise ProblemError(INVALID_REQUEST, "Numbers must be finite.") from exc
            try:
                item = queries.create(query)
            except QueueFullError as exc:
                raise ProblemError(
                    QUEUE_FULL,
                    "Too many queries are waiting.",
                    headers={"Retry-After": str(retry_after_seconds)},
                ) from exc
            location = f"/katago/{katago_id}/queries/{item.id}"
            return query_response(item, 201, Location=location)

        @self.get("/katago/{katago_id}/queries/{query_id}")
        async def get_query(katago_id: str, query_id: str):
            item = katago(katago_id).get(query_id)
            if item is None:
                raise ProblemError(QUERY_NOT_FOUND, "Unknown query")
            return query_response(item)

        @self.delete("/katago/{katago_id}/queries/{query_id}", status_code=204)
        async def delete_query(katago_id: str, query_id: str) -> Response:
            if not await katago(katago_id).delete(query_id):
                raise ProblemError(QUERY_NOT_FOUND, "Unknown query")
            return Response(status_code=204)


def create_katago_router(
    settings: Mapping[str, KataGoSettings], **router_kwargs: Any
) -> KataGoRouter:
    """Build the routes for each configured KataGo.

    The router's lifespan starts every KataGo and stops them at shutdown.
    FastAPI merges it into the app's lifespan in ``include_router``.
    """
    katagos = {
        name: KataGoQueries(
            KataGoEngine(
                s.command,
                configs=s.configs,
                model=s.model,
                human_model=s.human_model,
                overrides=s.overrides,
            ),
            max_running=s.max_running,
            max_queued=s.max_queued,
            timeout_seconds=s.timeout_seconds,
            keep_seconds=s.keep_seconds,
            max_visits=s.max_visits,
        )
        for name, s in settings.items()
    }

    @asynccontextmanager
    async def lifespan(_: Any):
        started: list[KataGoQueries] = []
        try:
            for queries in katagos.values():
                # Added first, so a KataGo that fails while starting is stopped.
                started.append(queries)
                await queries.engine.start()
            yield
        finally:
            for queries in reversed(started):
                await queries.aclose()
                await queries.engine.aclose()

    return KataGoRouter(katagos, lifespan=lifespan, **router_kwargs)
