"""The analysis routes, against the fake engine."""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastgtp.katago.engine import KataGoEngine
from fastgtp.katago import queries as queries_module
from fastgtp.katago.queries import KataGoQueries
from fastgtp.katago.router import KataGoRouter
from fastgtp.server.problems import install_problem_handlers

FAKE = Path(__file__).with_name("fake_analysis.py")
PROBLEMS = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"
QUERY = {"rules": "japanese", "boardXSize": 9, "boardYSize": 9, "moves": []}
SLOW = {**QUERY, "maxVisits": 1_000_000}
BASE = "/katago/default"


@contextmanager
def client(*flags: str, **limits):
    engine = KataGoEngine(
        [sys.executable, str(FAKE), *flags], configs=["a.cfg"], model="m.bin.gz"
    )
    queries = KataGoQueries(engine, **limits)

    @asynccontextmanager
    async def lifespan(_):
        await engine.start()
        yield
        await queries.aclose()
        await engine.aclose()

    app = FastAPI(lifespan=lifespan)
    install_problem_handlers(app)
    app.include_router(KataGoRouter({"default": queries}))
    with TestClient(app) as c:
        yield c


def wait(c: TestClient, location: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = c.get(location).json()
        if body["status"] in ("SUCCEEDED", "FAILED"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"{location} did not finish")


def assert_problem(res, status: int, slug: str) -> dict:
    assert res.status_code == status
    assert res.headers["content-type"] == "application/problem+json"
    assert res.json()["type"] == PROBLEMS + slug
    return res.json()


def test_list_version_and_models():
    with client() as c:
        assert c.get("/katago").json() == {"items": [{"id": "default"}]}
        assert c.get(f"{BASE}/version").json()["version"] == "1.0.0"
        assert c.get(f"{BASE}/models").json()["models"][0]["name"] == "fake.bin.gz"
        for res in (
            c.get("/katago/other/version"),
            c.get("/katago/other/models"),
            c.post("/katago/other/queries", json=QUERY),
            c.get("/katago/other/queries/x"),
            c.delete("/katago/other/queries/x"),
        ):
            assert_problem(res, 404, "katago-not-found")


def test_query_succeeds():
    with client() as c:
        res = c.post(f"{BASE}/queries", json={**QUERY, "analyzeTurns": [0, 2, 1]})
        assert res.status_code == 201
        assert res.headers["retry-after"] == "1"
        created = res.json()
        assert res.headers["location"] == f"{BASE}/queries/{created['id']}"
        assert created["status"] in ("QUEUED", "RUNNING")
        assert created["query"] == {**QUERY, "analyzeTurns": [0, 2, 1]}

        # null means the same as a missing field.
        with_null = c.post(f"{BASE}/queries", json={**QUERY, "komi": None})
        assert with_null.json()["query"] == QUERY

        body = wait(c, res.headers["location"])
        assert body["status"] == "SUCCEEDED"
        assert [r["turnNumber"] for r in body["responses"]] == [0, 1, 2]
        assert {r["id"] for r in body["responses"]} == {created["id"]}
        assert "error" not in body and body["startedAt"] and body["finishedAt"]
        assert "retry-after" not in c.get(res.headers["location"]).headers


def test_invalid_queries_are_400():
    nan_rules = (
        '{"rules": {"komi": NaN}, "boardXSize": 9, "boardYSize": 9, "moves": []}'
    )
    with client(max_visits=100) as c:
        for body, field in [
            ({**QUERY, "overrideSettings": {}}, "overrideSettings"),
            ({**QUERY, "analyzeTurns": []}, "analyzeTurns"),
            ({**QUERY, "moves": [["X", "E5"]]}, "moves[0][0]"),
            ({**QUERY, "maxVisits": 101}, "maxVisits"),
            ({**QUERY, "boardXSize": "9"}, "boardXSize"),
            ({**QUERY, "includeOwnership": "yes"}, "includeOwnership"),
            ({**QUERY, "komi": True}, "komi"),
        ]:
            res = c.post(f"{BASE}/queries", json=body)
            assert assert_problem(res, 400, "invalid-request")["field"] == field
        res = c.post(
            f"{BASE}/queries",
            content=nan_rules,
            headers={"content-type": "application/json"},
        )
        assert_problem(res, 400, "invalid-request")


def test_rejected_query_fails_with_the_error():
    with client() as c:
        res = c.post(f"{BASE}/queries", json={**QUERY, "moves": [["B", "Z99"]]})
        body = wait(c, res.headers["location"])
        assert body["status"] == "FAILED"
        assert body["error"] == {
            "error": "Could not parse board location: Z99",
            "field": "moves",
        }


def test_full_queue_is_503():
    with client(max_queued=1) as c:
        first = c.post(f"{BASE}/queries", json=SLOW).headers["location"]
        # Wait until the first runs, so the second is the only one queued.
        deadline = time.monotonic() + 10
        while c.get(first).json()["status"] == "QUEUED":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert c.post(f"{BASE}/queries", json=SLOW).json()["status"] == "QUEUED"
        res = c.post(f"{BASE}/queries", json=SLOW)
        assert_problem(res, 503, "queue-full")
        assert res.headers["retry-after"] == "5"


def test_query_that_runs_too_long_is_terminated():
    with client(timeout_seconds=0.2) as c:
        res = c.post(f"{BASE}/queries", json=SLOW)
        body = wait(c, res.headers["location"])
        assert body["status"] == "FAILED"
        assert body["error"]["error"] == "The query ran longer than the server allows."
        # The turn being searched kept what it found.
        assert len(body["responses"]) == 1


def test_stuck_terminate_still_frees_the_slot(monkeypatch):
    monkeypatch.setattr(queries_module, "_TERMINATE_WAIT_SECONDS", 0.2)
    with client("--ignore-terminate", timeout_seconds=0.2) as c:
        stuck = c.post(f"{BASE}/queries", json=SLOW).headers["location"]
        deleted = c.post(f"{BASE}/queries", json=SLOW).headers["location"]
        assert wait(c, stuck)["status"] == "FAILED"
        # Deleting a running query also sends terminate, and must not hang.
        deadline = time.monotonic() + 10
        while c.get(deleted).json()["status"] != "RUNNING":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert c.delete(deleted).status_code == 204


def test_delete_frees_the_slot():
    with client() as c:
        running = c.post(f"{BASE}/queries", json=SLOW).headers["location"]
        queued = c.post(f"{BASE}/queries", json=SLOW).headers["location"]
        after = c.post(f"{BASE}/queries", json=QUERY).headers["location"]
        for location in (queued, running):
            assert c.delete(location).status_code == 204
            assert_problem(c.get(location), 404, "query-not-found")
            assert_problem(c.delete(location), 404, "query-not-found")
        assert wait(c, after)["status"] == "SUCCEEDED"


def test_finished_queries_are_removed_later():
    with client(keep_seconds=0.1) as c:
        location = c.post(f"{BASE}/queries", json=QUERY).headers["location"]
        wait(c, location)
        time.sleep(0.3)
        assert_problem(c.get(location), 404, "query-not-found")


def test_engine_stop_fails_the_query():
    with client("--exit-after-queries", "1") as c:
        location = c.post(f"{BASE}/queries", json=QUERY).headers["location"]
        body = wait(c, location)
        assert body["status"] == "FAILED"
        assert body["error"] == {"error": "KataGo stopped before the query finished."}
