import pytest

from fastapi import FastAPI

ENDPOINT_KEY_PAIRS = [
    ("name", "name"),
    ("version", "version"),
    ("protocol_version", "protocol_version"),
]


@pytest.mark.parametrize(["endpoint", "key"], ENDPOINT_KEY_PAIRS)
def test_get(client, session_id, endpoint, key):
    res = client.get(f"/{session_id}/{endpoint}")
    assert res.status_code == 200
    assert key in res.json()


@pytest.mark.parametrize(["endpoint", "key"], ENDPOINT_KEY_PAIRS)
def test_return_404_with_invalid_session_id(client, invalid_session_id, endpoint, key):
    res = client.get(f"/{invalid_session_id}/{endpoint}")
    assert res.status_code == 404


def test_open_session(client):
    res = client.post("/open_session")
    assert res.status_code == 201
    assert "session_id" in res.json()


def test_quit_session(client):
    open_res = client.post("/open_session")
    assert open_res.status_code == 201
    new_session_id = open_res.json()["session_id"]

    quit_res = client.post(f"/{new_session_id}/quit")
    assert quit_res.status_code == 200
    assert quit_res.json() == {"closed": True}
