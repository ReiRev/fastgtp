"""The kinds of error the ``/v1`` routes report.

Each kind has a ``type`` URI, as RFC 9457 describes, so clients can tell the
errors apart without reading the title. ``docs/problems.md`` describes each
kind at the anchor its URI names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_TYPE_BASE = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"


@dataclass(frozen=True, slots=True)
class ProblemType:
    """One kind of error, with the status and title it is always sent with."""

    status: int
    title: str
    slug: str | None = None

    @property
    def uri(self) -> str:
        """Return the ``type`` URI, or ``about:blank`` for a plain HTTP error."""
        return _TYPE_BASE + self.slug if self.slug else "about:blank"

    def body(self, detail: str, **extra: Any) -> dict[str, Any]:
        """Return a problem details object of this kind."""
        return {
            "type": self.uri,
            "title": self.title,
            "status": self.status,
            "detail": detail,
            **extra,
        }


INVALID_REQUEST = ProblemType(422, "Invalid request", "invalid-request")
UNKNOWN_PROFILE = ProblemType(422, "Unknown profile", "unknown-profile")
TOO_MANY_TURNS = ProblemType(422, "Too many turns", "too-many-turns")
IDEMPOTENCY_KEY_REUSED = ProblemType(
    422, "Idempotency key reused", "idempotency-key-reused"
)
ANALYSIS_NOT_SUPPORTED = ProblemType(
    501, "Analysis not supported", "analysis-not-supported"
)
QUEUE_FULL = ProblemType(503, "Queue full", "queue-full")
UNKNOWN_JOB = ProblemType(404, "Unknown job", "unknown-job")
ILLEGAL_MOVE = ProblemType(422, "Illegal move", "illegal-move")
ILLEGAL_SETUP = ProblemType(422, "Illegal setup", "illegal-setup")
ENGINE_ERROR = ProblemType(502, "Engine error", "engine-error")
ANALYSIS_TIMED_OUT = ProblemType(504, "Analysis timed out", "analysis-timed-out")
INTERNAL_ERROR = ProblemType(500, "Internal error", "internal-error")
