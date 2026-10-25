"""Convenience module for running fastgtp with `fastapi dev` or uvicorn.

Usage example:

    FASTGTP_ENGINE="katago --gtp" fastapi dev fastgtp/server/main.py

Set at least one of these environment variables:

- `FASTGTP_ENGINE`: the GTP engine command (string or JSON array). Enables the
  session-based GTP routes.
- `FASTGTP_PROFILES`: path to a TOML file of analysis profiles. Enables the
  `/v1` analysis routes.

These optional variables tune analysis jobs:

- `FASTGTP_MAX_RUNNING_JOBS` (default 2)
- `FASTGTP_MAX_QUEUED_JOBS` (default 100)
- `FASTGTP_JOB_TIMEOUT_SECONDS` (default 1800)
- `FASTGTP_JOB_RETENTION_SECONDS` (default 3600)
- `FASTGTP_RETRY_AFTER_SECONDS` (default 5)

The module exposes a module-level `app` object so tooling such as
`fastapi dev fastgtp/server/main.py` or `uvicorn fastgtp.server.main:app` can pick it up.
"""

from __future__ import annotations

import os

from . import GTPTransportManager, SubprocessGTPTransport, create_app
from .profiles import load_profiles
from .v1 import AnalysisService, JobSettings


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1, got {raw!r}")
    return value


command = os.environ.get("FASTGTP_ENGINE")
profiles_path = os.environ.get("FASTGTP_PROFILES")
if command is None and profiles_path is None:
    raise RuntimeError(
        "Set FASTGTP_ENGINE, FASTGTP_PROFILES, or both to launch the server."
    )

manager = (
    GTPTransportManager(SubprocessGTPTransport(command))
    if command is not None
    else None
)

analysis = None
if profiles_path is not None:
    defaults = JobSettings()
    analysis = AnalysisService(
        load_profiles(profiles_path),
        JobSettings(
            max_running=_positive_int("FASTGTP_MAX_RUNNING_JOBS", defaults.max_running),
            max_queued=_positive_int("FASTGTP_MAX_QUEUED_JOBS", defaults.max_queued),
            timeout_seconds=_positive_int(
                "FASTGTP_JOB_TIMEOUT_SECONDS", int(defaults.timeout_seconds)
            ),
            retention_seconds=_positive_int(
                "FASTGTP_JOB_RETENTION_SECONDS", int(defaults.retention_seconds)
            ),
            retry_after_seconds=_positive_int(
                "FASTGTP_RETRY_AFTER_SECONDS", defaults.retry_after_seconds
            ),
        ),
    )

app = create_app(manager, analysis=analysis)
