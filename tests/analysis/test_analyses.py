from __future__ import annotations

import hashlib
import time

import pytest

from .helpers import wait_for_job, wait_for_status

GAME = {
    "profile": "test-v1",
    "board": {"width": 19, "height": 19},
    "rules": "japanese",
    "komi": 6.5,
    "setup": [{"color": "B", "point": "D4"}, {"color": "B", "point": "q16"}],
    "moves": [{"color": "W", "point": "Q4"}, {"color": "B", "point": "pass"}],
}


def submit(client, body=None, **headers):
    return client.post("/v1/analyses", json=body or GAME, headers=headers)


def fake_winrate(moves_played: int, to_play: str) -> float:
    return round(0.5 + 0.01 * moves_played + (0.001 if to_play == "W" else 0.0), 6)


def test_analysis_returns_black_winrate_for_every_turn(make_client, tmp_path):
    client = make_client()

    res = submit(client)
    assert res.status_code == 202
    job = res.json()
    assert res.headers["location"] == f"/v1/analyses/{job['id']}"
    assert res.headers["retry-after"] == "5"
    assert job["status"] in ("queued", "running")
    assert job["progress"]["total"] == 3

    done = wait_for_job(client, job["id"])
    assert done["status"] == "succeeded"
    assert done["progress"] == {"done": 3, "total": 3}
    result = done["result"]
    assert result["profile"] == "test-v1"
    assert result["turns"] == [
        {"turn": 0, "blackWinrate": fake_winrate(0, "W")},
        {"turn": 1, "blackWinrate": fake_winrate(1, "B")},
        {"turn": 2, "blackWinrate": fake_winrate(2, "W")},
    ]
    conditions = result["conditions"]
    assert conditions["engine"] == {"name": "FakeEngine", "version": "0.1"}
    assert conditions["model"] == {
        "name": "model",
        "sha256": hashlib.sha256(b"fake network").hexdigest(),
    }
    assert conditions["visits"] == 50
    assert len(conditions["configSha256"]) == 64
    assert "retry-after" not in client.get(f"/v1/analyses/{job['id']}").headers


def test_analysis_sends_the_game_as_gtp_commands(make_client, engine_log):
    client = make_client({"test-v1": ["--log", str(engine_log)]})

    job = submit(client).json()
    wait_for_job(client, job["id"])

    analysis_run = engine_log.read_text().split("argv ")[-1].splitlines()
    assert analysis_run[0].endswith(
        "-override-config maxVisits=50,reportAnalysisWinratesAs=BLACK"
    )
    assert analysis_run[1:] == [
        "boardsize 19",
        "clear_board",
        "kata-set-rules japanese",
        "komi 6.5",
        "set_position B D4 B Q16",
        "kata-search_analyze W interval 100000 rootInfo true",
        "play W Q4",
        "kata-search_analyze B interval 100000 rootInfo true",
        "play B pass",
        "kata-search_analyze W interval 100000 rootInfo true",
    ]


def test_analysis_stops_replaying_after_the_last_requested_turn(
    make_client, engine_log
):
    client = make_client({"test-v1": ["--log", str(engine_log)]})

    job = submit(client, {**GAME, "turns": [0]}).json()
    done = wait_for_job(client, job["id"])

    assert done["result"]["turns"] == [
        {"turn": 0, "blackWinrate": fake_winrate(0, "W")}
    ]
    assert not any(
        line.startswith("play") for line in engine_log.read_text().splitlines()
    )


def test_rectangular_board_and_initial_player(make_client, engine_log):
    client = make_client({"test-v1": ["--log", str(engine_log)]})
    body = {
        **GAME,
        "board": {"width": 9, "height": 13},
        "setup": [],
        "initialPlayer": "W",
        "moves": [],
        "komi": 0,
    }

    done = wait_for_job(client, submit(client, body).json()["id"])

    assert done["result"]["turns"] == [
        {"turn": 0, "blackWinrate": fake_winrate(0, "W")}
    ]
    log = engine_log.read_text().splitlines()
    assert "rectangular_boardsize 9 13" in log
    assert "komi 0" in log
    assert not any(line.startswith("set_position") for line in log)


def test_illegal_move_fails_the_job_with_its_index(make_client):
    client = make_client()
    body = {
        **GAME,
        "moves": [{"color": "W", "point": "Q4"}, {"color": "B", "point": "D4"}],
    }

    done = wait_for_job(client, submit(client, body).json()["id"])

    assert done["status"] == "failed"
    assert "result" not in done
    assert done["error"] == {
        "type": "about:blank",
        "title": "Illegal move",
        "status": 422,
        "detail": "moves[1]: B D4 is illegal",
        "field": "moves[1]",
    }


def test_engine_without_the_extensions_is_rejected(make_client):
    client = make_client({"test-v1": [], "plain-v1": ["--without", "set_position"]})

    res = submit(client, {**GAME, "profile": "plain-v1"})

    assert res.status_code == 501
    assert res.headers["content-type"] == "application/problem+json"
    assert "set_position" in res.json()["detail"]
    profiles = {p["name"]: p for p in client.get("/v1/profiles").json()["profiles"]}
    assert profiles["plain-v1"]["available"] is False
    assert profiles["test-v1"]["available"] is True
    assert profiles["test-v1"]["limits"] == {"maxTurns": 10}


def test_unknown_profile_is_404(make_client):
    client = make_client()

    res = submit(client, {**GAME, "profile": "missing"})

    assert res.status_code == 404
    assert res.headers["content-type"] == "application/problem+json"
    assert res.json()["title"] == "Unknown profile"


@pytest.mark.parametrize(
    "change",
    [
        {"komi": 6.3},
        {"rules": "ing"},
        {"visits": 1000},
        {"moves": [{"color": "W", "point": "T20"}]},
        {"setup": [{"color": "B", "point": "pass"}]},
        {"setup": [{"color": "B", "point": "D4"}, {"color": "W", "point": "D4"}]},
        {"turns": [3]},
        {"board": {"width": 25, "height": 25}},
    ],
)
def test_invalid_request_is_a_422_problem(make_client, change):
    client = make_client()

    res = submit(client, {**GAME, **change})

    assert res.status_code == 422
    assert res.headers["content-type"] == "application/problem+json"
    body = res.json()
    assert body["title"] == "Invalid request"
    assert body["errors"]


def test_too_many_turns_is_rejected(make_client):
    client = make_client(max_turns=2)

    res = submit(client)

    assert res.status_code == 422
    assert res.json()["field"] == "turns"


def test_full_queue_is_503_with_retry_after(make_client):
    client = make_client(
        {"test-v1": ["--analyze-seconds", "2"]}, max_running=1, max_queued=1
    )

    first = submit(client).json()
    wait_for_status(client, first["id"], "running")
    second = submit(client)
    third = submit(client)

    assert second.status_code == 202
    assert third.status_code == 503
    assert third.headers["retry-after"] == "5"
    assert client.get("/v1/health").json() == {
        "status": "ok",
        "runningJobs": 1,
        "queuedJobs": 1,
        "maxRunningJobs": 1,
        "maxQueuedJobs": 1,
    }


def test_cancel_stops_a_running_job(make_client):
    client = make_client({"test-v1": ["--analyze-seconds", "30"]})
    job = submit(client).json()
    wait_for_status(client, job["id"], "running")

    started = time.monotonic()
    res = client.delete(f"/v1/analyses/{job['id']}")

    assert res.status_code == 204
    assert time.monotonic() - started < 10
    assert client.get(f"/v1/analyses/{job['id']}").json()["status"] == "canceled"
    assert client.get("/v1/health").json()["runningJobs"] == 0


def test_cancel_of_a_queued_job(make_client):
    client = make_client({"test-v1": ["--analyze-seconds", "30"]}, max_running=1)
    running = submit(client).json()
    wait_for_status(client, running["id"], "running")
    queued = submit(client).json()

    assert client.delete(f"/v1/analyses/{queued['id']}").status_code == 204
    assert client.get(f"/v1/analyses/{queued['id']}").json()["status"] == "canceled"
    assert client.get(f"/v1/analyses/{running['id']}").json()["status"] == "running"


def test_unknown_job_is_404(make_client):
    client = make_client()

    assert client.get("/v1/analyses/nope").status_code == 404
    res = client.delete("/v1/analyses/nope")
    assert res.status_code == 404
    assert res.headers["content-type"] == "application/problem+json"


def test_job_timeout_fails_with_504(make_client):
    client = make_client({"test-v1": ["--analyze-seconds", "30"]}, timeout_seconds=1)

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "failed"
    assert done["error"]["status"] == 504


def test_engine_crash_fails_with_its_stderr(make_client):
    client = make_client({"test-v1": ["--exit-on-analyze", "2"]})

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "failed"
    assert done["error"]["status"] == 502
    assert "fake engine crashed on purpose" in done["error"]["detail"]
    assert done["progress"]["done"] == 1


def test_engine_that_floods_stderr_does_not_block(make_client):
    # More than a pipe buffer holds, so an unread stderr would stall the engine.
    client = make_client({"test-v1": ["--stderr-bytes", "500000"]}, timeout_seconds=10)

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "succeeded"


def test_same_idempotency_key_returns_the_same_job(make_client):
    client = make_client()

    first = submit(client, **{"Idempotency-Key": "game-1"}).json()
    again = submit(client, **{"Idempotency-Key": "game-1"}).json()
    other = submit(client, {**GAME, "komi": 7.5}, **{"Idempotency-Key": "game-1"})

    assert again["id"] == first["id"]
    assert other.status_code == 422
    assert other.json()["title"] == "Idempotency key reused"


def test_v1_routes_take_precedence_over_gtp_sessions(make_client):
    client = make_client(with_gtp=True)

    assert client.get("/v1/health").json()["status"] == "ok"
    session_id = client.post("/open_session").json()["session_id"]
    assert client.get(f"/{session_id}/name").json() == {"name": "FakeEngine"}
    client.post(f"/{session_id}/quit")


def test_gtp_routes_keep_their_validation_format(make_client):
    client = make_client(with_gtp=True)
    session_id = client.post("/open_session").json()["session_id"]

    res = client.post(f"/{session_id}/komi", json={"value": "much"})

    assert res.status_code == 422
    assert res.headers["content-type"] == "application/json"
    assert "detail" in res.json()
    client.post(f"/{session_id}/quit")
