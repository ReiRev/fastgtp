"""Errors as RFC 9457 problem details.

Each kind of error has a ``type`` URI that points to its section in
``docs/problems.md``, so clients can tell errors apart without reading the
title or the detail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_BASE = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"


@dataclass(frozen=True, slots=True)
class ProblemType:
    """One kind of error, with the status and title it is always sent with."""

    status: int
    title: str
    slug: str

    @property
    def uri(self) -> str:
        return _TYPE_BASE + self.slug


INVALID_REQUEST = ProblemType(400, "Invalid request", "invalid-request")
SESSION_NOT_FOUND = ProblemType(404, "Session not found", "session-not-found")
ENGINE_ERROR = ProblemType(500, "Engine error", "engine-error")
INTERNAL_ERROR = ProblemType(500, "Internal error", "internal-error")


class ProblemError(Exception):
    """An error that is sent to the client as a problem of ``kind``."""

    def __init__(
        self,
        kind: ProblemType,
        detail: str,
        *,
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.field = field
        self.headers = headers


def problem_response(
    *,
    type_uri: str,
    title: str,
    status: int,
    detail: str,
    field: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_uri,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if field is not None:
        body["field"] = field
    return JSONResponse(
        body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers
    )


def _field_path(loc: tuple[Any, ...]) -> str | None:
    # FastAPI prefixes the location with where it came from ("body", "path").
    # Clients only need the part inside, as in "moves[10].vertex".
    path = ""
    for part in loc[1:]:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or None


def install_problem_handlers(app: FastAPI) -> None:
    """Send every 4xx and 5xx error of ``app`` as problem details."""

    async def problem_handler(_: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            type_uri=exc.kind.uri,
            title=exc.kind.title,
            status=exc.kind.status,
            detail=exc.detail,
            field=exc.field,
            headers=exc.headers,
        )

    async def validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's own errors echo the input back, which can be most of a
        # large body, so only the first location and message are returned.
        errors = exc.errors()
        first = errors[0] if errors else {"loc": (), "msg": "Invalid request"}
        return problem_response(
            type_uri=INVALID_REQUEST.uri,
            title=INVALID_REQUEST.title,
            status=INVALID_REQUEST.status,
            detail=str(first["msg"]),
            field=_field_path(tuple(first["loc"])),
        )

    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Raised by the framework itself, for an unknown path or a wrong method.
        # These have no fastgtp type, so RFC 9457's about:blank is used.
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "Error"
        return problem_response(
            type_uri="about:blank",
            title=title,
            status=exc.status_code,
            detail=str(exc.detail),
            headers=exc.headers,
        )

    async def unexpected_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return problem_response(
            type_uri=INTERNAL_ERROR.uri,
            title=INTERNAL_ERROR.title,
            status=INTERNAL_ERROR.status,
            detail="fastgtp failed to handle the request.",
        )

    app.add_exception_handler(ProblemError, problem_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_handler)
    app.add_exception_handler(Exception, unexpected_handler)
