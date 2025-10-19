def test_open_session(client):
    res = client.post("/open_session")
    assert res.status_code == 201

    payload = res.json()
    assert "session_id" in payload
    session_id = payload["session_id"]

    cleanup = client.post(f"/{session_id}/quit")
    assert cleanup.status_code == 200
    assert cleanup.json() == {"closed": True}


def test_quit_session(client):
    open_res = client.post("/open_session")
    assert open_res.status_code == 201
    session_id = open_res.json()["session_id"]

    quit_res = client.post(f"/{session_id}/quit")
    assert quit_res.status_code == 200
    assert quit_res.json() == {"closed": True}

    res = client.get(f"/{session_id}/name")
    assert res.status_code == 404
