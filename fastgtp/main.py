"""Convenience module for running fastgtp with `fastapi dev` or uvicorn.

Usage example:

    FASTGTP_ENGINE="katago --gtp" FASTGTP_MODEL_NAME="katago" fastapi dev fastgtp/main.py

Set the `FASTGTP_ENGINE` environment variable to the engine command (string or
JSON array) and optionally `FASTGTP_MODEL_NAME` for the prefix. When
`FASTGTP_ENGINE` is not provided this module falls back to
`FASTGTP_DEFAULT_ENGINE`, which is populated automatically inside the provided
Docker image.

The module exposes a module-level `app` object so tooling such as
`fastapi dev fastgtp/main.py` or `uvicorn fastgtp.main:app` can pick it up.
"""
from __future__ import annotations

import json
import os
from typing import Sequence

from . import create_app


def _read_engine_command(env_value: str) -> Sequence[str] | str:
    env_value = env_value.strip()
    if not env_value:
        raise ValueError("FASTGTP_ENGINE cannot be empty")

    if env_value.startswith("["):
        return tuple(json.loads(env_value))

    return env_value



def _resolve_engine_command() -> Sequence[str] | str:
    raw_command = os.environ.get("FASTGTP_ENGINE")
    if raw_command is None:
        raw_command = os.environ.get("FASTGTP_DEFAULT_ENGINE")
    if raw_command is None:
        raise RuntimeError(
            "FASTGTP_ENGINE environment variable is required to launch the dev "
            "server (or set FASTGTP_DEFAULT_ENGINE)."
        )

    return _read_engine_command(raw_command)

model_name = os.environ.get("FASTGTP_MODEL_NAME", "model")

app = create_app(
    model_name=model_name,
    executable=_resolve_engine_command(),
)
