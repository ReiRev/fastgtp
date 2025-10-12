from fastapi import FastAPI


def test_open_session(client):
    res = client.post("/open_session")
    assert res.status_code == 201
    assert "session_id" in res.json()


def test_get_name(client, session_id):
    res = client.get(f"/{session_id}/name")
    assert res.status_code == 200
