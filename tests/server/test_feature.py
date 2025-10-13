import pytest

ENDPOINT_KEY_PAIRS = [
    ("name", "name"),
    ("version", "version"),
    ("protocol_version", "protocol_version"),
]


@pytest.mark.parametrize(
    ["endpoint", "key"],
    [
        ("name", "name"),
        ("version", "version"),
        ("protocol_version", "protocol_version"),
    ],
)
def test_get(client, session_id, endpoint, key):
    res = client.get(f"/{session_id}/{endpoint}")
    assert res.status_code == 200
    assert key in res.json()

    res = client.get(f"/invalid_session_id/{endpoint}")
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


def test_list_commands(client, session_id):
    res = client.get(f"/{session_id}/commands")
    assert res.status_code == 200

    data = res.json()
    assert "commands" in data
    commands = data["commands"]
    assert isinstance(commands, list)

    expected_subset = {"protocol_version", "name", "version", "list_commands", "quit"}
    assert expected_subset.issubset(set(commands))


def test_set_boardsize_square(client, session_id):
    res = client.post(f"/{session_id}/boardsize", json={"x": 19})
    assert res.status_code == 200

    data = res.json()
    assert "message" in data
    assert isinstance(data["message"], str)


def test_set_boardsize_rectangular(client, session_id):
    res = client.post(f"/{session_id}/boardsize", json={"x": 9, "y": 13})
    assert res.status_code == 200

    data = res.json()
    assert "message" in data
    assert isinstance(data["message"], str)


def test_set_boardsize_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/boardsize", json={"x": 19})
    assert res.status_code == 404


def test_set_komi(client, session_id):
    res = client.post(f"/{session_id}/komi", json={"value": 6.5})
    assert res.status_code == 200

    data = res.json()
    assert "message" in data
    assert isinstance(data["message"], str)


def test_set_komi_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/komi", json={"value": 6.5})
    assert res.status_code == 404
