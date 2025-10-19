def test_open_session(client):
    res = client.post("/open_session")
    assert res.status_code == 201

    payload = res.json()
    assert "session_id" in payload
    session_id = payload["session_id"]

    cleanup = client.post(f"/{session_id}/quit")
    assert cleanup.status_code == 200
    assert cleanup.json() == {"closed": True}
