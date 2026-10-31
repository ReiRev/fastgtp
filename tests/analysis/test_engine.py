"""The analysis engine wrapper, against a fake engine.

The folder and test names avoid the word that CI uses to deselect the tests
that need the real engine.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from fastgtp.katago.engine import STOPPED_ERROR, KataGoEngine

FAKE = Path(__file__).with_name("fake_analysis.py")
QUERY = {"rules": "japanese", "komi": 6.5, "boardXSize": 9, "boardYSize": 9}
WAIT = 10


def engine(*flags: str, **kwargs) -> KataGoEngine:
    kwargs.setdefault("configs", ["analysis.cfg"])
    kwargs.setdefault("model", "model.bin.gz")
    return KataGoEngine([sys.executable, str(FAKE), *flags], **kwargs)


def run(scenario, *flags: str, **kwargs):
    """Run ``scenario`` with a started engine, and close the engine after."""

    async def wrapped():
        e = engine(*flags, **kwargs)
        await e.start()
        try:
            return await scenario(e)
        finally:
            await e.aclose()

    return asyncio.run(asyncio.wait_for(wrapped(), WAIT))


async def finish(e: KataGoEngine, query: dict):
    running = await e.submit(query)
    await running.done.wait()
    return running


def test_start_reads_version_and_models():
    async def scenario(e):
        return e.version, e.models

    version, models = run(scenario)
    assert version == {"version": "1.0.0", "git_hash": "fake"}
    # Without the directory the fake engine reports.
    assert models[0]["name"] == "fake.bin.gz"


def test_command_line_forces_black_view(tmp_path):
    argv_file = tmp_path / "argv.json"

    async def scenario(e):
        pass

    run(
        scenario,
        "--argv-file",
        str(argv_file),
        configs=["a.cfg", "b.cfg"],
        model="m.bin.gz",
        human_model="h.bin.gz",
        overrides={"reportAnalysisWinratesAs": "SIDETOMOVE", "maxVisits": "50"},
    )
    assert json.loads(argv_file.read_text()) == [
        "analysis",
        "-config",
        "a.cfg",
        "-config",
        "b.cfg",
        "-model",
        "m.bin.gz",
        "-human-model",
        "h.bin.gz",
        "-override-config",
        "reportAnalysisWinratesAs=BLACK,maxVisits=50",
    ]


def test_override_that_cannot_be_passed():
    with pytest.raises(ValueError):
        engine(overrides={"maxVisits": "1,maxTime=9"})


def test_each_turn_answered_once():
    async def scenario(e):
        return await finish(e, {**QUERY, "analyzeTurns": [0, 1, 1]})

    running = run(scenario)
    assert running.error is None
    assert sorted(r["turnNumber"] for r in running.responses) == [0, 1]


def test_without_turns_the_last_is_analyzed():
    async def scenario(e):
        return await finish(e, {**QUERY, "moves": [["B", "E5"]]})

    assert [r["turnNumber"] for r in run(scenario).responses] == [1]


def test_empty_turns_are_refused():
    async def scenario(e):
        with pytest.raises(ValueError):
            await e.submit({**QUERY, "analyzeTurns": []})

    run(scenario)


def test_queries_that_cannot_be_sent_are_refused():
    async def scenario(e):
        for query in ({**QUERY, "komi": float("nan")}, {**QUERY, "action": "x"}):
            with pytest.raises(ValueError):
                await e.submit(query)
        return await finish(e, QUERY)

    assert run(scenario).error is None


def test_cancelled_terminate_leaves_the_engine_working():
    async def scenario(e):
        slow = await e.submit({**QUERY, "maxVisits": 1_000_000})
        terminating = asyncio.create_task(e.terminate(slow))
        # The terminate line is written in the same step that registers it.
        while not e._actions:
            await asyncio.sleep(0)
        terminating.cancel()
        await slow.done.wait()
        return slow, await finish(e, QUERY)

    slow, after = run(scenario)
    assert slow.error is None
    assert after.error is None and len(after.responses) == 1


def test_queries_get_their_own_responses():
    async def scenario(e):
        slow = await e.submit({**QUERY, "maxVisits": 1_000_000})
        fast = await finish(e, {**QUERY, "maxVisits": 7})
        assert not slow.done.is_set()
        return fast

    assert [r["rootInfo"]["visits"] for r in run(scenario).responses] == [7]


def test_error_ends_the_query():
    async def scenario(e):
        return await finish(e, {**QUERY, "moves": [["B", "Z99"]]})

    running = run(scenario)
    assert running.error["field"] == "moves"
    assert running.responses == []


def test_warning_does_not_end_the_query():
    async def scenario(e):
        return await finish(e, {**QUERY, "unknownField": 1})

    running = run(scenario)
    assert running.error is None
    assert running.warnings[0]["field"] == "unknownField"
    assert len(running.responses) == 1


def test_terminate_keeps_turns_that_started():
    async def scenario(e):
        running = await e.submit(
            {**QUERY, "analyzeTurns": [0, 1, 2], "maxVisits": 1_000_000}
        )
        await e.terminate(running)
        await running.done.wait()
        return running

    running = run(scenario)
    assert running.error is None
    # The turns that had not started reported noResults and are left out.
    assert [r["turnNumber"] for r in running.responses] == [0]


def test_crash_fails_open_queries_and_restarts():
    async def scenario(e):
        slow = await e.submit({**QUERY, "maxVisits": 1_000_000})
        crashed = await finish(e, QUERY)
        await slow.done.wait()
        return slow, crashed, await finish(e, QUERY)

    slow, crashed, after = run(scenario, "--exit-after-queries", "2")
    assert slow.error == STOPPED_ERROR
    assert crashed.error == STOPPED_ERROR
    assert after.error is None and len(after.responses) == 1


def test_close_fails_open_queries():
    async def scenario():
        e = engine()
        await e.start()
        running = await e.submit({**QUERY, "maxVisits": 1_000_000})
        await e.aclose()
        return running

    running = asyncio.run(asyncio.wait_for(scenario(), WAIT))
    assert running.error == STOPPED_ERROR
