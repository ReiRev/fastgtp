"""Convenience module for running fastgtp with `fastapi dev` or uvicorn.

Usage example:

    FASTGTP_ENGINE="katago --gtp" fastapi dev fastgtp/server/main.py

Set the `FASTGTP_ENGINE` environment variable to the engine command (string or
JSON array).

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

manager = GTPTransportManager(SubprocessGTPTransport(command))

app = create_app(manager)
