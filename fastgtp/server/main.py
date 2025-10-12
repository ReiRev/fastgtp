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

from . import (
    GTPTransportManager,
    SubprocessGTPTransport,
    create_app,
    get_transport_manager,
)


def build_transport(command: str) -> SubprocessGTPTransport:
    """Construct a transport for the configured engine command."""
    return SubprocessGTPTransport(command)


command = os.environ.get("FASTGTP_ENGINE")
if command is None:
    raise RuntimeError(
        "FASTGTP_ENGINE environment variable is required to launch the server."
    )


def transport_factory() -> SubprocessGTPTransport:
    return build_transport(command)


manager = GTPTransportManager(transport_factory)


async def override_get_manager() -> GTPTransportManager:
    return manager


app = create_app()
app.dependency_overrides[get_transport_manager] = override_get_manager


@app.on_event("shutdown")
async def _close_sessions() -> None:
    await manager.close_all()
