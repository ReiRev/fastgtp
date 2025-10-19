def test_quit_session(client):
    open_res = client.post("/open_session")
    assert open_res.status_code == 201
    session_id = open_res.json()["session_id"]

    quit_res = client.post(f"/{session_id}/quit")
    assert quit_res.status_code == 200
    assert quit_res.json() == {"closed": True}
