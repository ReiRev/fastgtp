"""Versioned HTTP API for analysis jobs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Header, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from .analysis import (
    AnalysisFailure,
    AnalysisRequest,
    EngineInfo,
    analyze_winrates,
    probe_engine,
)
from .jobs import IdempotencyConflict, Job, JobManager, JobStatus, QueueFull
from .problems import (
    ANALYSIS_NOT_SUPPORTED,
    ENGINE_ERROR,
    IDEMPOTENCY_KEY_REUSED,
    INVALID_REQUEST,
    QUEUE_FULL,
    TOO_MANY_TURNS,
    UNKNOWN_JOB,
    UNKNOWN_PROFILE,
    ProblemType,
)
from .profiles import Profile
from .transport import SubprocessGTPTransport

logger = logging.getLogger(__name__)

PREFIX = "/v1"
PROBLEM_MEDIA_TYPE = "application/problem+json"
_PROBE_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class JobSettings:
    """Limits for analysis jobs."""

    max_running: int = 2
    max_queued: int = 100
    timeout_seconds: float = 1800.0
    retention_seconds: float = 3600.0
    retry_after_seconds: int = 5


class AnalysisService:
    """Profiles, the engines behind them, and the jobs that use them."""

    def __init__(
        self, profiles: dict[str, Profile], settings: JobSettings | None = None
    ) -> None:
        self.profiles = profiles
        self.settings = settings or JobSettings()
        self.engines: dict[str, EngineInfo] = {}
        self._jobs: JobManager | None = None

    @property
    def jobs(self) -> JobManager:
        """Return the job manager. It exists once the service has started."""
        if self._jobs is None:
            raise RuntimeError("AnalysisService.start() has not run")
        return self._jobs

    async def start(self) -> None:
        """Start each profile's engine once to learn what it supports."""
        for profile in self.profiles.values():
            transport = SubprocessGTPTransport(profile.engine_command(), respawn=False)
            try:
                await transport.open()
                engine = await asyncio.wait_for(
                    probe_engine(transport), _PROBE_TIMEOUT_SECONDS
                )
            except AnalysisFailure as failure:
                raise RuntimeError(
                    f"Profile {profile.name!r}: engine did not start: {failure.detail}"
                ) from failure
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    f"Profile {profile.name!r}: engine did not answer within "
                    f"{_PROBE_TIMEOUT_SECONDS:g} seconds"
                ) from exc
            # After the timeout, because TimeoutError is an OSError on
            # Python 3.11 and later.
            except OSError as exc:
                raise RuntimeError(
                    f"Profile {profile.name!r}: engine did not start: {exc}"
                ) from exc
            finally:
                await transport.aclose()
            if engine.missing_commands:
                logger.warning(
                    "Profile %r cannot analyze; the engine lacks %s",
                    profile.name,
                    sorted(engine.missing_commands),
                )
            self.engines[profile.name] = engine
        self._jobs = JobManager(
            max_running=self.settings.max_running,
            max_queued=self.settings.max_queued,
            timeout_seconds=self.settings.timeout_seconds,
            retention_seconds=self.settings.retention_seconds,
        )

    async def close(self) -> None:
        """Cancel the jobs that have not finished."""
        if self._jobs is not None:
            await self._jobs.close()

    def conditions(self, profile: Profile) -> dict[str, Any]:
        """Return everything about a profile that decides its results."""
        engine = self.engines[profile.name]
        return {
            "engine": {"name": engine.name, "version": engine.version},
            "model": {"name": profile.model_name, "sha256": profile.model_sha256},
            "configSha256": profile.config_sha256,
            "visits": profile.visits,
        }

    def runner(self, profile: Profile, request: AnalysisRequest):
        """Return the coroutine function that runs one analysis job."""

        async def run(on_progress) -> dict[str, Any]:
            transport = SubprocessGTPTransport(profile.engine_command(), respawn=False)
            try:
                try:
                    await transport.open()
                except OSError as exc:
                    logger.warning(
                        "Profile %r: engine did not start: %s", profile.name, exc
                    )
                    raise AnalysisFailure(
                        ENGINE_ERROR, "The engine could not be started"
                    ) from exc
                turns = await analyze_winrates(transport, request, on_progress)
            finally:
                await transport.aclose()
            return {
                "profile": profile.name,
                "conditions": self.conditions(profile),
                "turns": turns,
            }

        return run


class Problem(BaseModel):
    """An RFC 9457 problem details object."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str


_RETRY_AFTER_HEADER = {
    "description": "Seconds to wait before trying again.",
    "schema": {"type": "integer"},
}


def _problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    responses: dict[int | str, dict[str, Any]] = {
        status: {
            "description": HTTPStatus(status).phrase,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": Problem.model_json_schema()}},
        }
        for status in statuses
    }
    if 503 in responses:
        responses[503]["headers"] = {"Retry-After": _RETRY_AFTER_HEADER}
    return responses


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Progress(_CamelModel):
    done: int
    total: int


class EngineConditions(_CamelModel):
    name: str
    version: str


class ModelConditions(_CamelModel):
    name: str
    sha256: str


class Conditions(_CamelModel):
    """Everything about a profile that decides its results."""

    engine: EngineConditions
    model: ModelConditions
    config_sha256: str
    visits: int


class TurnResult(_CamelModel):
    turn: int
    black_winrate: float


class AnalysisResult(_CamelModel):
    profile: str
    conditions: Conditions
    turns: list[TurnResult]


class JobResponse(_CamelModel):
    """The state of an analysis job."""

    id: str
    status: JobStatus
    progress: Progress
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: AnalysisResult | None = None
    error: Problem | None = None


class ProfileResponse(_CamelModel):
    name: str
    available: bool
    conditions: Conditions
    limits: dict[str, int]


class ProfilesResponse(_CamelModel):
    profiles: list[ProfileResponse]


class HealthResponse(_CamelModel):
    status: Literal["ok"]
    running_jobs: int
    queued_jobs: int
    max_running_jobs: int
    max_queued_jobs: int


def problem_response(
    kind: ProblemType,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """Build an RFC 9457 problem details response."""
    return JSONResponse(
        jsonable_encoder(kind.body(detail, **extra)),
        status_code=kind.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def install_problem_handler(app: FastAPI) -> None:
    """Report errors on ``/v1`` paths as problem details.

    Other routes keep FastAPI's default error responses, so existing clients
    see no change.
    """

    async def validation_handler(request: Request, exc: RequestValidationError):
        if not _is_v1(request):
            return await request_validation_exception_handler(request, exc)
        # FastAPI's errors also echo the invalid input, which can be most of a
        # large body, so only the location and the message are returned.
        errors = [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return problem_response(
            INVALID_REQUEST,
            "The request body or parameters are not valid.",
            errors=errors,
        )

    async def http_handler(request: Request, exc: StarletteHTTPException):
        if not _is_v1(request):
            return await http_exception_handler(request, exc)
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "Error"
        headers = exc.headers
        if exc.status_code == 405:
            # Starlette lists only the methods of the first route that matches
            # the path, but several routes can share it.
            headers = {**(headers or {}), "Allow": _allowed_methods(request)}
        plain = ProblemType(exc.status_code, title)
        return problem_response(plain, str(exc.detail), headers=headers)

    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_handler)


def create_v1_router(service: AnalysisService) -> APIRouter:
    """Create the ``/v1`` routes backed by ``service``."""

    router = APIRouter(prefix=PREFIX, tags=["analysis"])
    retry_after = str(service.settings.retry_after_seconds)

    def job_response(job: Job, response: Response) -> JobResponse:
        if not job.finished:
            response.headers["Retry-After"] = retry_after
        return JobResponse(
            id=job.id,
            status=job.status,
            progress=Progress(done=job.done, total=job.total),
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            result=job.result,
            error=job.error,
        )

    def unknown_job() -> JSONResponse:
        return problem_response(UNKNOWN_JOB, "No job has this id")

    @router.post(
        "/analyses",
        status_code=202,
        response_model=JobResponse,
        response_model_exclude_none=True,
        responses={
            202: {
                "description": "The job is queued.",
                "headers": {
                    "Location": {
                        "description": "URL of the job.",
                        "schema": {"type": "string"},
                    },
                    "Retry-After": _RETRY_AFTER_HEADER,
                },
            },
            **_problems(422, 501, 503),
        },
    )
    async def submit_analysis(  # type: ignore[unused-coroutine]
        request: AnalysisRequest,
        http_request: Request,
        response: Response,
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=255
        ),
    ):
        """Queue a win rate analysis of a game."""
        profile = service.profiles.get(request.profile)
        if profile is None:
            return problem_response(
                UNKNOWN_PROFILE,
                f"No profile named {request.profile!r}",
                field="profile",
            )
        missing = service.engines[profile.name].missing_commands
        if missing:
            return problem_response(
                ANALYSIS_NOT_SUPPORTED,
                f"The engine of profile {profile.name!r} lacks {sorted(missing)}",
            )
        if request.turn_count > profile.max_turns:
            return problem_response(
                TOO_MANY_TURNS,
                f"Profile {profile.name!r} analyzes at most {profile.max_turns} turns per job",
                field="moves",
            )

        fingerprint = hashlib.sha256(
            request.model_dump_json(by_alias=True).encode("utf-8")
        ).hexdigest()
        try:
            job = service.jobs.submit(
                service.runner(profile, request),
                fingerprint=fingerprint,
                total=request.turn_count,
                idempotency_key=idempotency_key,
            )
        except QueueFull:
            return problem_response(
                QUEUE_FULL,
                "Too many jobs are waiting. Try again later.",
                headers={"Retry-After": retry_after},
            )
        except IdempotencyConflict:
            return problem_response(
                IDEMPOTENCY_KEY_REUSED,
                "This Idempotency-Key was already used for a different request.",
            )

        response.headers["Location"] = str(
            http_request.url_for("get_analysis", job_id=job.id).path
        )
        return job_response(job, response)

    @router.get(
        "/analyses/{job_id}",
        response_model=JobResponse,
        response_model_exclude_none=True,
        responses={
            200: {"headers": {"Retry-After": _RETRY_AFTER_HEADER}},
            **_problems(404, 422),
        },
    )
    async def get_analysis(job_id: str, response: Response):  # type: ignore[unused-coroutine]
        """Return the state of a job, with its result once it has finished."""
        job = service.jobs.get(job_id)
        if job is None:
            return unknown_job()
        return job_response(job, response)

    @router.delete("/analyses/{job_id}", status_code=204, responses=_problems(404, 422))
    async def delete_analysis(job_id: str):  # type: ignore[unused-coroutine]
        """Delete a job. A job that has not finished is stopped first."""
        if not await service.jobs.delete(job_id):
            return unknown_job()
        return Response(status_code=204)

    @router.get("/profiles", response_model=ProfilesResponse)
    async def list_profiles():  # type: ignore[unused-coroutine]
        """List the profiles and the conditions each one fixes."""
        return ProfilesResponse(
            profiles=[
                ProfileResponse(
                    name=profile.name,
                    available=not service.engines[profile.name].missing_commands,
                    conditions=service.conditions(profile),
                    limits={"maxTurns": profile.max_turns},
                )
                for profile in service.profiles.values()
            ]
        )

    @router.get("/health", response_model=HealthResponse)
    async def health():  # type: ignore[unused-coroutine]
        """Report job counts without starting an engine."""
        jobs = service.jobs
        return HealthResponse(
            status="ok",
            running_jobs=jobs.running_count,
            queued_jobs=jobs.queued_count,
            max_running_jobs=service.settings.max_running,
            max_queued_jobs=service.settings.max_queued,
        )

    return router


def _allowed_methods(request: Request) -> str:
    methods: set[str] = set()
    for route in request.app.router.routes:
        if (
            isinstance(route, APIRoute)
            and route.matches(request.scope)[0] != Match.NONE
        ):
            methods |= route.methods
    return ", ".join(sorted(methods))


def _is_v1(request: Request) -> bool:
    # Servers such as uvicorn put the root path in front of the request path,
    # so it is removed before the path is compared.
    path = request.scope["path"]
    root_path = request.scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :]
    return path == PREFIX or path.startswith(PREFIX + "/")
