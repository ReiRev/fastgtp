"""Every error is sent as RFC 9457 problem details."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from fastgtp import GTPTransportManager, SubprocessGTPTransport, create_app

PROBLEMS = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"
SECRET = "stderr: secret path"


class FakeTransport:
    """Answers each command from a fixed table, without starting a process."""

    def __init__(self, replies: dict[str, Any]):
        self._replies = replies

    async def open(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    def copy(self) -> FakeTransport:
        return FakeTransport(self._replies)

    async def send_command(self, command: str) -> str:
        reply = self._replies[command.split()[0]]
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(command)
        return reply


@pytest.fixture
def replies() -> dict[str, Any]:
    # A healthy engine. Tests replace a reply to make one command fail.
    return {
        "name": "= Fake\n\n",
        "version": "= 1\n\n",
        "protocol_version": "= 2\n\n",
        "list_commands": "= name\n\n",
        "printsgf": "= (;SZ[19])\n\n",
        "get_komi": "= 6.5\n\n",
    }


@pytest.fixture
def client(replies):
    # The transport keeps a reference to the table, so changes made by a test
    # after the session exists still apply.
    app = create_app(GTPTransportManager(FakeTransport(replies)))

    @app.get("/broken")
    async def broken():
        raise ValueError(SECRET)

    # The server error middleware re-raises after sending the response, which
    # the test client would turn into a test failure.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def session_id(client):
    return client.post("/sessions").json()["session_id"]


def assert_problem(res, status: int, type_uri: str) -> dict:
    assert res.status_code == status
    assert res.headers["content-type"] == "application/problem+json"
    body = res.json()
    assert body["type"] == type_uri
    assert body["status"] == status
    assert body["title"]
    assert SECRET not in res.text
    return body


def test_unknown_session(client):
    res = client.get("/sessions/no-such-session")
    assert_problem(res, 404, PROBLEMS + "session-not-found")


def test_engine_failure_reply(client, replies, session_id):
    replies["name"] = "? cannot tell\n\n"
    res = client.get(f"/sessions/{session_id}")
    body = assert_problem(res, 500, PROBLEMS + "engine-error")
    assert body["detail"] == "cannot tell"


def test_engine_exception_hides_stderr(client, replies, session_id):
    replies["name"] = RuntimeError(SECRET)
    res = client.get(f"/sessions/{session_id}")
    body = assert_problem(res, 500, PROBLEMS + "engine-error")
    assert body["detail"] == "The engine did not answer the command."


def test_engine_that_does_not_start():
    app = create_app(
        GTPTransportManager(SubprocessGTPTransport("/nonexistent/engine --mode gtp"))
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.post("/sessions")
    body = assert_problem(res, 500, PROBLEMS + "engine-error")
    assert "nonexistent" not in res.text
    assert body["detail"] == "The engine could not be started."


def test_failed_start_does_not_leave_a_session(replies):
    # With a limit of one, a leftover session would make this a 503.
    manager = GTPTransportManager(FakeTransport(replies), max_sessions=1)
    with TestClient(create_app(manager), raise_server_exceptions=False) as c:
        replies["name"] = "garbage\n\n"
        assert c.post("/sessions").status_code == 500
        replies["name"] = "= Fake\n\n"
        assert c.post("/sessions").status_code == 201


def test_unreadable_reply(client, replies, session_id):
    replies["name"] = "garbage\n\n"
    res = client.get(f"/sessions/{session_id}")
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_unknown_path(client):
    body = assert_problem(client.get("/no/such/path"), 404, "about:blank")
    assert body["title"] == "Not Found"


def test_wrong_method(client):
    res = client.patch("/sessions")
    assert_problem(res, 405, "about:blank")
    assert "POST" in res.headers["allow"]


def test_unexpected_error(client):
    res = client.get("/broken")
    assert_problem(res, 500, PROBLEMS + "internal-error")


def test_validation_error_is_400_with_field(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"size": 1, "komi": 0})
    body = assert_problem(res, 400, PROBLEMS + "invalid-request")
    assert body["field"] == "size"


def test_wrong_type_is_not_echoed(client, session_id):
    res = client.put(
        f"/sessions/{session_id}/board", json={"size": "huge-input", "komi": 0}
    )
    body = assert_problem(res, 400, PROBLEMS + "invalid-request")
    assert body["field"] == "size"
    assert "huge-input" not in res.text


def test_malformed_json_has_no_field(client, session_id):
    res = client.put(
        f"/sessions/{session_id}/board",
        content='{"size": 9,',
        headers={"content-type": "application/json"},
    )
    body = assert_problem(res, 400, PROBLEMS + "invalid-request")
    assert "field" not in body


def test_sgf_error_hides_temp_path(client, replies, session_id):
    # GNU Go names the file it could not load.
    replies["loadsgf"] = lambda command: f"? cannot load '{command.split()[1]}'\n\n"
    res = client.put(f"/sessions/{session_id}/board", json={"sgf": "(;SZ[99])"})
    body = assert_problem(res, 400, PROBLEMS + "invalid-request")
    assert body["detail"] == "cannot load the SGF"


def test_unreadable_komi(client, replies, session_id):
    replies["get_komi"] = "= not a number\n\n"
    res = client.get(f"/sessions/{session_id}/board")
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_resignation_is_upper_case(client, replies, session_id):
    replies["genmove"] = "= resign\n\n"
    res = client.post(f"/sessions/{session_id}/moves", json={"color": "BLACK"})
    assert res.status_code == 201
    assert res.json() == {"color": "BLACK", "vertex": "RESIGN"}


def test_unreadable_generated_move(client, replies, session_id):
    replies["genmove"] = "= somewhere\n\n"
    res = client.post(f"/sessions/{session_id}/moves", json={"color": "BLACK"})
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_play_without_answer(client, replies, session_id):
    replies["play"] = RuntimeError(SECRET)
    res = client.post(
        f"/sessions/{session_id}/moves", json={"color": "BLACK", "vertex": "D4"}
    )
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_undo_without_answer(client, replies, session_id):
    replies["undo"] = RuntimeError(SECRET)
    res = client.delete(f"/sessions/{session_id}/moves/last")
    assert_problem(res, 500, PROBLEMS + "engine-error")
