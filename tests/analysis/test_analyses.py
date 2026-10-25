from __future__ import annotations

import hashlib
import os
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
        "type": "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#illegal-move",
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


def test_unknown_profile_is_422(make_client):
    client = make_client()

    res = submit(client, {**GAME, "profile": "missing"})

    assert res.status_code == 422
    assert res.headers["content-type"] == "application/problem+json"
    assert res.json()["title"] == "Unknown profile"
    assert res.json()["field"] == "profile"


@pytest.mark.parametrize(
    "change",
    [
        {"komi": 6.3},
        {"rules": "ing"},
        {"visits": 1000},
        {"moves": [{"color": "W", "point": "T20"}]},
        {"setup": [{"color": "B", "point": "pass"}]},
        {"setup": [{"color": "B", "point": "D4"}, {"color": "W", "point": "D4"}]},
        {"turns": [0]},
        {"board": {"width": 25, "height": 25}},
        {"initialPlayer": "B"},
        {"moves": [{"color": "B", "point": "pass"}] * 1001},
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
    assert all(set(error) == {"loc", "msg", "type"} for error in body["errors"])


def test_too_many_turns_is_rejected(make_client):
    client = make_client(max_turns=2)

    res = submit(client)

    assert res.status_code == 422
    assert res.json()["field"] == "moves"


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


def test_delete_stops_a_running_job(make_client):
    client = make_client({"test-v1": ["--analyze-seconds", "30"]})
    job = submit(client).json()
    wait_for_status(client, job["id"], "running")

    started = time.monotonic()
    res = client.delete(f"/v1/analyses/{job['id']}")

    assert res.status_code == 204
    assert time.monotonic() - started < 10
    assert client.get(f"/v1/analyses/{job['id']}").status_code == 404
    assert client.get("/v1/health").json()["runningJobs"] == 0


def test_delete_of_a_queued_job(make_client):
    client = make_client({"test-v1": ["--analyze-seconds", "30"]}, max_running=1)
    running = submit(client).json()
    wait_for_status(client, running["id"], "running")
    queued = submit(client).json()

    assert client.delete(f"/v1/analyses/{queued['id']}").status_code == 204
    assert client.get(f"/v1/analyses/{queued['id']}").status_code == 404
    assert client.get(f"/v1/analyses/{running['id']}").json()["status"] == "running"


def test_delete_of_a_finished_job_removes_it(make_client):
    client = make_client()
    job = submit(client, **{"Idempotency-Key": "game-1"}).json()
    wait_for_job(client, job["id"])

    assert client.delete(f"/v1/analyses/{job['id']}").status_code == 204
    assert client.get(f"/v1/analyses/{job['id']}").status_code == 404
    again = submit(client, **{"Idempotency-Key": "game-1"}).json()
    assert again["id"] != job["id"]


def test_finished_job_is_dropped_after_retention(make_client):
    client = make_client(retention_seconds=0.5)
    job = submit(client).json()
    wait_for_job(client, job["id"])

    deadline = time.monotonic() + 10
    while (res := client.get(f"/v1/analyses/{job['id']}")).status_code == 200:
        assert time.monotonic() < deadline
        time.sleep(0.1)

    assert res.status_code == 404
    assert res.json()["title"] == "Unknown job"


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


def test_engine_crash_keeps_its_stderr_in_the_server_log(make_client, caplog):
    client = make_client({"test-v1": ["--exit-on-analyze", "2"]})

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "failed"
    assert done["error"]["status"] == 502
    assert "crashed" not in done["error"]["detail"]
    assert "fake engine crashed on purpose" in caplog.text
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


def test_v1_and_gtp_session_routes_work_together(make_client):
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


@pytest.mark.parametrize(
    "method, path, status",
    [
        ("get", "/v1/nope", 404),
        ("put", "/v1/analyses", 405),
        ("post", "/v1/health", 405),
    ],
)
def test_unknown_v1_routes_are_problems(make_client, method, path, status):
    client = make_client()

    res = client.request(method.upper(), path)

    assert res.status_code == status
    assert res.headers["content-type"] == "application/problem+json"
    assert res.json()["type"] == "about:blank"
    assert res.json()["status"] == status


def test_unknown_gtp_routes_keep_their_format(make_client):
    client = make_client(with_gtp=True)

    res = client.get("/nope/name")

    assert res.status_code == 404
    assert res.headers["content-type"] == "application/json"


def test_timeout_wins_over_an_engine_that_closed_its_output(make_client):
    client = make_client({"test-v1": ["--close-stdout-on-analyze"]}, timeout_seconds=1)

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "failed"
    assert done["error"]["status"] == 504


def test_search_without_root_info_fails_the_job(make_client):
    client = make_client({"test-v1": ["--no-root-info"]})

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "failed"
    assert done["error"]["detail"] == "kata-search_analyze returned no rootInfo winrate"


@pytest.mark.parametrize(
    "change, field",
    [
        ({"komi": 6.3}, "komi"),
        ({"moves": [{"color": "W", "point": "T20"}]}, "moves"),
        ({"setup": [{"color": "B", "point": "pass"}]}, "setup"),
        ({"initialPlayer": "B"}, "moves"),
    ],
)
def test_validation_errors_name_their_field(make_client, change, field):
    client = make_client()

    res = submit(client, {**GAME, **change})

    assert res.status_code == 422
    assert res.json()["errors"][0]["loc"] == ["body", field]


def test_long_strings_are_not_echoed_back(make_client):
    client = make_client()
    body = {
        **GAME,
        "profile": "p" * 100_000,
        "moves": [{"color": "B", "point": "x" * 100_000}],
    }

    res = submit(client, body)

    assert res.status_code == 422
    assert len(res.content) < 2000


def engine_pids(engine_log) -> list[int]:
    return [
        int(line.split()[1])
        for line in engine_log.read_text().splitlines()
        if line.startswith("pid ")
    ]


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize(
    "setup, first", [([], "B"), ([{"color": "B", "point": "D4"}], "W")]
)
def test_default_initial_player(make_client, engine_log, setup, first):
    client = make_client({"test-v1": ["--log", str(engine_log)]})

    wait_for_job(
        client, submit(client, {**GAME, "setup": setup, "moves": []}).json()["id"]
    )

    assert f"kata-search_analyze {first} interval 100000 rootInfo true" in (
        engine_log.read_text().splitlines()
    )


def test_delete_ends_the_engine_process(make_client, engine_log):
    client = make_client(
        {"test-v1": ["--analyze-seconds", "30", "--log", str(engine_log)]}
    )
    job = submit(client).json()
    wait_for_status(client, job["id"], "running")

    client.delete(f"/v1/analyses/{job['id']}")

    assert not is_running(engine_pids(engine_log)[-1])


def test_shutdown_ends_running_engines(make_client, engine_log):
    client = make_client(
        {"test-v1": ["--analyze-seconds", "30", "--log", str(engine_log)]}
    )
    job = submit(client).json()
    wait_for_status(client, job["id"], "running")
    pid = engine_pids(engine_log)[-1]

    client.__exit__(None, None, None)

    assert not is_running(pid)


def test_refused_setup_fails_the_job_on_the_setup_field(make_client):
    client = make_client({"test-v1": ["--reject-setup"]})

    done = wait_for_job(client, submit(client).json()["id"])

    assert done["status"] == "failed"
    assert done["error"]["status"] == 422
    assert done["error"]["field"] == "setup"


def test_405_lists_every_method_of_the_path(make_client):
    client = make_client()

    res = client.patch("/v1/analyses/some-id")

    assert res.status_code == 405
    assert res.headers["allow"] == "DELETE, GET"


def test_location_keeps_the_root_path(make_client):
    client = make_client(root_path="/gtp")

    res = submit(client)

    assert res.headers["location"] == f"/gtp/v1/analyses/{res.json()['id']}"


def test_empty_idempotency_key_is_rejected(make_client):
    client = make_client()

    res = submit(client, **{"Idempotency-Key": ""})

    assert res.status_code == 422


def test_komi_must_be_a_number(make_client):
    client = make_client()

    assert submit(client, {**GAME, "komi": True}).status_code == 422
    assert submit(client, {**GAME, "komi": 7}).status_code == 202


def test_unknown_job_does_not_echo_its_id(make_client):
    client = make_client()

    res = client.get("/v1/analyses/" + "a" * 10_000)

    assert res.status_code == 404
    assert len(res.content) < 500
