from __future__ import annotations

import asyncio

import pytest

from fastgtp import (
    AnalysisService,
    ProfileError,
    SubprocessGTPTransport,
    create_app,
    load_profiles,
)
from fastgtp.server import transport as transport_module
from fastgtp.server import v1 as v1_module
from fastgtp.server.jobs import JobManager

from .helpers import fake_engine_command


def test_create_app_needs_gtp_or_analysis():
    with pytest.raises(ValueError):
        create_app()


@pytest.mark.parametrize(
    "table, message",
    [
        ('visits = 10\nmaxTurns = 1\nconfig = "a.cfg"\ncommand = "x"', "model"),
        (
            'command = "x"\nmodel = "m.bin"\nconfig = "a.cfg"\nvisits = 0\nmaxTurns = 1',
            "visits",
        ),
        (
            'command = "x"\nmodel = "m.bin"\nconfig = "missing.cfg"\nvisits = 1\nmaxTurns = 1',
            "does not exist",
        ),
        (
            'command = "x"\nmodel = "m.bin"\nconfig = "a.cfg"\nvisits = 1\nmaxTurns = 1\nmaxVisits = 5',
            "unknown keys",
        ),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path, table, message):
    (tmp_path / "m.bin").write_bytes(b"m")
    (tmp_path / "a.cfg").write_text("")
    path = tmp_path / "profiles.toml"
    path.write_text(f'[profiles."p-v1"]\n{table}\n')

    with pytest.raises(ProfileError, match=message):
        load_profiles(path)


def test_profile_name_must_be_simple(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text('[profiles."Bad Name"]\n')

    with pytest.raises(ProfileError, match="lowercase"):
        load_profiles(path)


def test_config_hash_covers_the_forced_visits(tmp_path):
    (tmp_path / "m.bin").write_bytes(b"m")
    (tmp_path / "a.cfg").write_text("same file\n")
    path = tmp_path / "profiles.toml"
    path.write_text(
        "".join(
            f'[profiles."v{visits}"]\ncommand = "x"\nmodel = "m.bin"\n'
            f'config = "a.cfg"\nvisits = {visits}\nmaxTurns = 1\n'
            for visits in (100, 200)
        )
    )

    profiles = load_profiles(path)

    assert profiles["v100"].config_sha256 != profiles["v200"].config_sha256


def test_config_hash_covers_the_command_arguments(tmp_path):
    (tmp_path / "m.bin").write_bytes(b"m")
    (tmp_path / "a.cfg").write_text("same file\n")
    path = tmp_path / "profiles.toml"
    path.write_text(
        "".join(
            f'[profiles."{name}"]\ncommand = "{command}"\nmodel = "m.bin"\n'
            f'config = "a.cfg"\nvisits = 1\nmaxTurns = 1\n'
            for name, command in (
                ("plain", "/a/katago gtp"),
                ("moved", "/b/katago gtp"),
                ("extra", "/a/katago gtp -override-config x=1"),
            )
        )
    )

    profiles = load_profiles(path)

    assert profiles["plain"].config_sha256 == profiles["moved"].config_sha256
    assert profiles["plain"].config_sha256 != profiles["extra"].config_sha256


def test_engine_that_ignores_sigterm_is_killed_despite_repeated_cancels(
    monkeypatch,
):
    monkeypatch.setattr(transport_module, "_TERMINATE_GRACE_SECONDS", 0.5)

    async def scenario():
        transport = SubprocessGTPTransport(fake_engine_command("--ignore-sigterm"))
        await transport.open()
        process = transport._process
        # Let the engine install its SIGTERM handler before it is closed.
        await transport.send_command("name")

        closing = asyncio.create_task(transport.aclose())
        await asyncio.sleep(0.1)
        closing.cancel()
        await asyncio.sleep(0.1)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing

        await asyncio.wait_for(process.wait(), 5)
        assert process.returncode == -9

    asyncio.run(scenario())


def test_finished_jobs_are_dropped_after_retention():
    async def scenario():
        now = [0.0]
        jobs = JobManager(
            max_running=1,
            max_queued=10,
            timeout_seconds=10,
            retention_seconds=60,
            clock=lambda: now[0],
        )

        async def runner(on_progress):
            on_progress(1)
            return {"turns": []}

        job = jobs.submit(runner, fingerprint="f", total=1, idempotency_key="k")
        await job.task
        assert jobs.get(job.id).status == "succeeded"

        now[0] = 59.0
        assert jobs.get(job.id) is not None
        now[0] = 60.0
        assert jobs.get(job.id) is None

        fresh = jobs.submit(runner, fingerprint="g", total=1, idempotency_key="k")
        assert fresh.id != job.id
        await jobs.close()

    asyncio.run(scenario())


def test_jobs_that_will_start_at_once_do_not_fill_the_queue():
    async def scenario():
        jobs = JobManager(
            max_running=2, max_queued=1, timeout_seconds=10, retention_seconds=60
        )

        async def runner(on_progress):
            await asyncio.sleep(10)
            return {}

        jobs.submit(runner, fingerprint="a", total=1)
        jobs.submit(runner, fingerprint="b", total=1)
        jobs.submit(runner, fingerprint="c", total=1)
        await asyncio.sleep(0)
        assert jobs.running_count == 2
        assert jobs.queued_count == 1
        await jobs.close()

    asyncio.run(scenario())


def test_startup_fails_when_the_engine_does_not_answer(write_profiles, monkeypatch):
    monkeypatch.setattr(v1_module, "_PROBE_TIMEOUT_SECONDS", 0.5)
    service = AnalysisService(
        load_profiles(write_profiles({"t": ["--hang-on", "name"]}))
    )

    with pytest.raises(RuntimeError, match="did not answer"):
        asyncio.run(service.start())


def test_startup_fails_when_the_engine_errors(write_profiles):
    service = AnalysisService(
        load_profiles(write_profiles({"t": ["--without", "name"]}))
    )

    with pytest.raises(RuntimeError, match="did not start"):
        asyncio.run(service.start())


@pytest.mark.parametrize("respawn", [True, False])
def test_engine_that_exited_is_replaced_only_with_respawn(respawn):
    async def scenario():
        transport = SubprocessGTPTransport(
            fake_engine_command("--exit-after-play", "1"), respawn=respawn
        )
        await transport.open()
        first = transport._process
        await transport.send_command("play B D4")
        await first.wait()
        try:
            if respawn:
                assert (await transport.send_command("name")).startswith("=")
                assert transport._process is not first
            else:
                with pytest.raises(RuntimeError, match="terminated"):
                    await transport.send_command("name")
        finally:
            await transport.aclose()

    asyncio.run(scenario())
