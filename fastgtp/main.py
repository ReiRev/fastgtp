"""Convenience module for running fastgtp with `fastapi dev` or uvicorn.

Usage example:

    FASTGTP_ENGINE="katago --gtp" FASTGTP_MODEL_NAME="katago" fastapi dev fastgtp/main.py

Set the `FASTGTP_ENGINE` environment variable to the engine command (string or
JSON array) and optionally `FASTGTP_MODEL_NAME` for the prefix.

The module exposes a module-level `app` object so tooling such as
`fastapi dev fastgtp/main.py` or `uvicorn fastgtp.main:app` can pick it up.
"""

from __future__ import annotations

import os
from . import SubprocessGTPTransport, create_app


command = os.environ.get("FASTGTP_ENGINE")
if command is None:
    raise RuntimeError(
        "FASTGTP_ENGINE environment variable is required to launch the server."
    )

app = create_app(SubprocessGTPTransport(command))
