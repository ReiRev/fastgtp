from __future__ import annotations

import asyncio

import pytest

from fastgtp import ProfileError, create_app, load_profiles
from fastgtp.server.jobs import JobManager


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
