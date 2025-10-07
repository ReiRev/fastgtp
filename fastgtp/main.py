"""Convenience module for running fastgtp with `fastapi dev` or uvicorn.

Usage example:

    FASTGTP_ENGINE="katago --gtp" FASTGTP_MODEL_NAME="katago" fastapi dev fastgtp/main.py

Set the `FASTGTP_ENGINE` environment variable to the engine command (string or
JSON array) and optionally `FASTGTP_MODEL_NAME` for the prefix.

The module exposes a module-level `app` object so tooling such as
`fastapi dev fastgtp/main.py` or `uvicorn fastgtp.main:app` can pick it up.
"""
from __future__ import annotations

import json
import os
from . import SubprocessGTPTransport, create_app


raw_command = os.environ.get("FASTGTP_ENGINE")
if raw_command is None:
    raise RuntimeError(
        "FASTGTP_ENGINE environment variable is required to launch the dev server."
    )

stripped_command = raw_command.strip()
if not stripped_command:
    raise ValueError("FASTGTP_ENGINE cannot be empty")

if stripped_command.startswith("["):
    command = tuple(json.loads(stripped_command))
else:
    command = stripped_command

model_name = os.environ.get("FASTGTP_MODEL_NAME", "model")

app = create_app(
    model_name=model_name,
    transport=SubprocessGTPTransport(command),
)
