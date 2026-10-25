from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from fastgtp import SubprocessGTPTransport
from fastgtp.server import transport as transport_module

STUB_ENGINE = Path(__file__).with_name("stub_engine.py")


def stub(*flags: str, respawn: bool = True) -> SubprocessGTPTransport:
    return SubprocessGTPTransport(
        [sys.executable, str(STUB_ENGINE), *flags], respawn=respawn
    )


def test_engine_that_floods_stderr_keeps_answering():
    async def scenario():
        # Each reply comes after more stderr than a pipe buffer holds.
        transport = stub("--stderr-bytes", "200000")
        try:
            for _ in range(3):
                reply = await asyncio.wait_for(transport.send_command("name"), 10)
                assert reply.startswith("= ok")
        finally:
            await transport.aclose()

    asyncio.run(scenario())


def test_reply_longer_than_64_kib_is_read():
    async def scenario():
        transport = stub("--line-bytes", "200000")
        try:
            reply = await transport.send_command("name")
        finally:
            await transport.aclose()
        return reply

    assert len(asyncio.run(scenario())) > 200000


def test_engine_that_ignores_sigterm_is_killed_when_close_is_cancelled(
    monkeypatch,
):
    monkeypatch.setattr(transport_module, "_TERMINATE_GRACE_SECONDS", 0.5)

    async def scenario():
        transport = stub("--ignore-sigterm")
        await transport.open()
        process = transport._process
        # Let the engine install its SIGTERM handler before it is closed.
        await transport.send_command("name")

        closing = asyncio.create_task(transport.aclose())
        await asyncio.sleep(0.1)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing

        await asyncio.wait_for(process.wait(), 5)
        assert process.returncode == -9

    asyncio.run(scenario())


@pytest.mark.parametrize("respawn", [True, False])
def test_engine_that_exited_is_replaced_only_with_respawn(respawn):
    async def scenario():
        transport = stub("--exit-after", "1", respawn=respawn)
        await transport.open()
        first = transport._process
        await transport.send_command("name")
        await first.wait()
        try:
            if respawn:
                assert (await transport.send_command("name")).startswith("= ok")
                assert transport._process is not first
            else:
                with pytest.raises(RuntimeError, match="terminated"):
                    await transport.send_command("name")
        finally:
            await transport.aclose()

    asyncio.run(scenario())


def test_copy_keeps_the_respawn_setting():
    assert stub(respawn=False).copy()._respawn is False
