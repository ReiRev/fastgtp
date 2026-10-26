"""Every error is sent as RFC 9457 problem details."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fastgtp import GTPTransportManager, create_app

PROBLEMS = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"
SECRET = "stderr: secret path"


class FakeTransport:
    """Answers each command from a fixed table, without starting a process."""

    def __init__(self, replies: dict[str, str | Exception]):
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
        return reply


@pytest.fixture
def client():
    transport = FakeTransport(
        {
            "name": "= Fake\n\n",
            "play": "? illegal move\n\n",
            "get_komi": "= not a number\n\n",
            "version": RuntimeError(SECRET),
            "protocol_version": "garbage\n\n",
        }
    )
    app = create_app(GTPTransportManager(transport))

    @app.get("/broken")
    async def broken():
        raise ValueError(SECRET)

    # The server error middleware re-raises after sending the response, which
    # the test client would turn into a test failure.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def session_id(client):
    return client.post("/open_session").json()["session_id"]


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
    res = client.get("/no-such-session/name")
    assert_problem(res, 404, PROBLEMS + "session-not-found")


def test_validation_error_is_400_with_field(client, session_id):
    res = client.post(f"/{session_id}/play", json={"color": "B", "vertex": "4D"})
    body = assert_problem(res, 400, PROBLEMS + "invalid-request")
    assert body["field"] == "vertex"
    # The invalid input is not echoed back.
    assert "4D" not in res.text


def test_missing_body_field(client, session_id):
    res = client.post(f"/{session_id}/play", json={"vertex": "D4"})
    body = assert_problem(res, 400, PROBLEMS + "invalid-request")
    assert body["field"] == "color"


def test_engine_failure_reply(client, session_id):
    res = client.post(f"/{session_id}/play", json={"color": "B", "vertex": "D4"})
    body = assert_problem(res, 500, PROBLEMS + "engine-error")
    assert body["detail"] == "illegal move"


def test_engine_exception_hides_stderr(client, session_id):
    res = client.get(f"/{session_id}/version")
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_unreadable_reply(client, session_id):
    res = client.get(f"/{session_id}/protocol_version")
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_unreadable_komi(client, session_id):
    res = client.get(f"/{session_id}/komi")
    assert_problem(res, 500, PROBLEMS + "engine-error")


def test_unknown_path(client):
    body = assert_problem(client.get("/no/such/path"), 404, "about:blank")
    assert body["title"] == "Not Found"


def test_wrong_method(client):
    res = client.delete("/open_session")
    assert_problem(res, 405, "about:blank")
    assert "POST" in res.headers["allow"]


def test_unexpected_error(client):
    res = client.get("/broken")
    assert_problem(res, 500, PROBLEMS + "internal-error")
