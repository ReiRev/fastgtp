"""Requests to one session run one at a time, and a delete waits for them."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from fastgtp import GTPTransportManager, create_app

REPLIES = {
    "name": "= Fake\n\n",
    "version": "= 1\n\n",
    "protocol_version": "= 2\n\n",
    "list_commands": "= name\n\n",
}


class SlowTransport:
    """Holds ``name`` until ``release`` is set, and counts engine starts."""

    starts = 0

    def __init__(self, release: asyncio.Event):
        self.release = release
        self.closed = False
        # Creating the session reads the name too, so holding starts later.
        self.hold = False

    async def open(self) -> None:
        SlowTransport.starts += 1

    async def aclose(self) -> None:
        self.closed = True

    def copy(self) -> SlowTransport:
        return SlowTransport(self.release)

    async def send_command(self, command: str) -> str:
        # A real transport would start a new engine here, which nothing tracks.
        assert not self.closed, "command sent to a closed transport"
        name = command.split()[0]
        if name == "name" and self.hold:
            await self.release.wait()
        return REPLIES[name]


@pytest.mark.anyio
async def test_delete_waits_for_running_request():
    release = asyncio.Event()
    SlowTransport.starts = 0
    manager = GTPTransportManager(SlowTransport(release))
    app = create_app(manager)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        session_id = (await c.post("/sessions")).json()["session_id"]
        url = f"/sessions/{session_id}"
        engine, _ = await manager.get_session(session_id)
        engine.hold = True

        running = asyncio.create_task(c.get(url))
        await asyncio.sleep(0.05)
        waiting = asyncio.create_task(c.get(url))
        await asyncio.sleep(0.05)
        deleting = asyncio.create_task(c.delete(url))
        await asyncio.sleep(0.05)
        assert not deleting.done()

        release.set()
        assert (await running).status_code == 200
        # It waited for the lock, and the session was gone when it got it.
        assert (await waiting).status_code == 404
        assert (await deleting).status_code == 204
    assert SlowTransport.starts == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"
