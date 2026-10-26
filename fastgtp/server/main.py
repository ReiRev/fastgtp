"""Convenience module for running fastgtp with `fastapi dev` or uvicorn.

Usage example:

    FASTGTP_ENGINE="katago --gtp" fastapi dev fastgtp/server/main.py

Set the `FASTGTP_ENGINE` environment variable to the engine command (string or
JSON array). Optional variables:

- `FASTGTP_MAX_SESSIONS` (8): the most engines that run at once. Each session
  is one engine process.
- `FASTGTP_RETRY_AFTER_SECONDS` (5): sent in `Retry-After` when the limit is
  reached.

The module exposes a module-level `app` object so tooling such as
`fastapi dev fastgtp/server/main.py` or `uvicorn fastgtp.server.main:app` can pick it up.
"""

from __future__ import annotations

import os

from . import GTPTransportManager, SubprocessGTPTransport, create_app

command = os.environ.get("FASTGTP_ENGINE")
if command is None:
    raise RuntimeError(
        "FASTGTP_ENGINE environment variable is required to launch the server."
    )


def _positive_int(name: str, default: int) -> int:
    value = os.environ.get(name, str(default))
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise RuntimeError(f"{name} must be a positive integer, not {value!r}.")
    return number


manager = GTPTransportManager(
    SubprocessGTPTransport(command),
    max_sessions=_positive_int("FASTGTP_MAX_SESSIONS", 8),
)

app = create_app(
    manager,
    retry_after_seconds=_positive_int("FASTGTP_RETRY_AFTER_SECONDS", 5),
)
