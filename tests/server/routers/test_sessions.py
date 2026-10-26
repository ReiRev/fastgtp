from fastapi.testclient import TestClient

from fastgtp import GTPTransportManager, SubprocessGTPTransport, create_app

PROBLEMS = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"


def test_create_read_delete(client):
    res = client.post("/sessions")
    assert res.status_code == 201
    session = res.json()
    session_id = session["session_id"]
    assert res.headers["location"] == f"/sessions/{session_id}"
    engine = session["engine"]
    assert engine["name"]
    assert engine["protocol_version"] == "2"
    assert "play" in engine["commands"]

    res = client.get(f"/sessions/{session_id}")
    assert res.status_code == 200
    assert res.json() == session

    res = client.delete(f"/sessions/{session_id}")
    assert res.status_code == 204
    assert res.content == b""

    res = client.get(f"/sessions/{session_id}")
    assert res.status_code == 404
    assert res.json()["type"] == PROBLEMS + "session-not-found"


def test_delete_unknown_session(client, invalid_session_id):
    res = client.delete(f"/sessions/{invalid_session_id}")
    assert res.status_code == 404
    assert res.json()["type"] == PROBLEMS + "session-not-found"


def test_session_limit():
    manager = GTPTransportManager(
        SubprocessGTPTransport("gnugo --mode gtp"), max_sessions=1
    )
    with TestClient(create_app(manager, retry_after_seconds=7)) as c:
        first = c.post("/sessions")
        assert first.status_code == 201

        res = c.post("/sessions")
        assert res.status_code == 503
        assert res.headers["retry-after"] == "7"
        assert res.json()["type"] == PROBLEMS + "too-many-sessions"

        # Deleting a session frees its place.
        c.delete(f"/sessions/{first.json()['session_id']}")
        assert c.post("/sessions").status_code == 201
