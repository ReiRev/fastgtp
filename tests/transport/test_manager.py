"""Session limit and per-session locking in GTPTransportManager."""

from __future__ import annotations

import asyncio

import pytest

from fastgtp import GTPTransportManager
from fastgtp.server.transport import TooManySessionsError


class FakeTransport:
    """Records whether it is open. ``aclose`` waits for ``close_gate``."""

    def __init__(self, close_gate: asyncio.Event | None = None):
        self.close_gate = close_gate
        self.open_count = 0
        self.closed = False

    async def open(self) -> None:
        self.open_count += 1

    async def aclose(self) -> None:
        if self.close_gate is not None:
            await self.close_gate.wait()
        self.closed = True

    def copy(self) -> FakeTransport:
        return FakeTransport(self.close_gate)

    async def send_command(self, command: str) -> str:
        return "= \n\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_limit_counts_open_sessions():
    manager = GTPTransportManager(FakeTransport(), max_sessions=1)
    session_id = await manager.open_session()
    with pytest.raises(TooManySessionsError):
        await manager.open_session()
    assert await manager.close_session(session_id)
    await manager.open_session()


@pytest.mark.anyio
async def test_limit_counts_sessions_that_are_still_closing():
    gate = asyncio.Event()
    manager = GTPTransportManager(FakeTransport(gate), max_sessions=1)
    session_id = await manager.open_session()
    closing = asyncio.create_task(manager.close_session(session_id))
    await asyncio.sleep(0.01)
    # The old engine has not stopped yet, so it still takes the one place.
    with pytest.raises(TooManySessionsError):
        await manager.open_session()
    gate.set()
    assert await closing
    await manager.open_session()


@pytest.mark.anyio
async def test_close_waits_for_the_session_lock():
    manager = GTPTransportManager(FakeTransport())
    session_id = await manager.open_session()
    transport, lock = await manager.get_session(session_id)
    async with lock:
        closing = asyncio.create_task(manager.close_session(session_id))
        await asyncio.sleep(0.01)
        # Gone from the table at once, but not closed while a request runs.
        assert not await manager.is_open(session_id, transport)
        assert not transport.closed
    assert await closing
    assert transport.closed


@pytest.mark.anyio
async def test_cancelled_close_still_closes():
    manager = GTPTransportManager(FakeTransport())
    session_id = await manager.open_session()
    transport, lock = await manager.get_session(session_id)
    async with lock:
        closing = asyncio.create_task(manager.close_session(session_id))
        await asyncio.sleep(0.01)
        closing.cancel()
    await asyncio.sleep(0.01)
    assert transport.closed


@pytest.mark.anyio
async def test_unknown_session():
    manager = GTPTransportManager(FakeTransport())
    with pytest.raises(KeyError):
        await manager.get_session("missing")
    assert not await manager.close_session("missing")
