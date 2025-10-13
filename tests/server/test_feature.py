from fastapi import FastAPI


def test_open_session(client):
    res = client.post("/open_session")
    assert res.status_code == 201
    assert "session_id" in res.json()


def test_get_name(client, session_id):
    res = client.get(f"/{session_id}/name")
    assert res.status_code == 200
    assert "name" in res.json()


def test_get_version(client, session_id):
    res = client.get(f"/{session_id}/version")
    assert res.status_code == 200
    assert "version" in res.json()


def test_get_protocol_version(client, session_id):
    res = client.get(f"/{session_id}/protocol_version")
    assert res.status_code == 200
    assert "protocol_version" in res.json()


def test_quit_session(client):
    open_res = client.post("/open_session")
    assert open_res.status_code == 201
    new_session_id = open_res.json()["session_id"]

    quit_res = client.post(f"/{new_session_id}/quit")
    assert quit_res.status_code == 200
    assert quit_res.json() == {"closed": True}
