import pytest

ENDPOINT_KEY_PAIRS = [
    ("name", "name"),
    ("version", "version"),
    ("protocol_version", "protocol_version"),
    ("komi", "komi"),
    ("sgf", "sgf"),
]


@pytest.mark.parametrize(
    ["endpoint", "key"],
    [
        ("name", "name"),
        ("version", "version"),
        ("protocol_version", "protocol_version"),
        ("komi", "komi"),
        ("sgf", "sgf"),
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
    assert "detail" in data
    assert isinstance(data["detail"], str)
    assert data["detail"] == "" or "Initializing board" in data["detail"]


def test_set_boardsize_rectangular(client, session_id):
    res = client.post(f"/{session_id}/boardsize", json={"x": 9, "y": 13})
    assert res.status_code == 200

    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


def test_set_boardsize_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/boardsize", json={"x": 19})
    assert res.status_code == 404


def test_set_komi(client, session_id):
    res = client.post(f"/{session_id}/komi", json={"value": 6.5})
    assert res.status_code == 200

    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


def test_set_komi_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/komi", json={"value": 6.5})
    assert res.status_code == 404


def test_play_move(client, session_id):
    boardsize_res = client.post(f"/{session_id}/boardsize", json={"x": 9})
    assert boardsize_res.status_code == 200

    res = client.post(f"/{session_id}/play", json={"color": "B", "vertex": "D4"})
    assert res.status_code == 200

    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


def test_play_move_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/play", json={"color": "B", "vertex": "D4"})
    assert res.status_code == 404


def test_play_move_invalid_color(client, session_id):
    res = client.post(f"/{session_id}/play", json={"color": "R", "vertex": "D4"})
    assert res.status_code == 422


def test_play_move_invalid_vertex(client, session_id):
    res = client.post(f"/{session_id}/play", json={"color": "B", "vertex": "19"})
    assert res.status_code == 422


def test_clear_board(client, session_id):
    res = client.post(f"/{session_id}/clear_board")
    assert res.status_code == 200

    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


def test_clear_board_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/clear_board")
    assert res.status_code == 404


def test_genmove(client, session_id):
    boardsize_res = client.post(f"/{session_id}/boardsize", json={"x": 9})
    assert boardsize_res.status_code == 200

    res = client.post(f"/{session_id}/genmove", json={"color": "B"})
    assert res.status_code == 200

    data = res.json()
    assert data.keys() == {"move"}
    assert isinstance(data["move"], str)
    assert data["move"]


def test_genmove_invalid_color(client, session_id):
    res = client.post(f"/{session_id}/genmove", json={"color": "R"})
    assert res.status_code == 422


def test_genmove_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/genmove", json={"color": "B"})
    assert res.status_code == 404


def test_get_sgf_format(client, session_id):
    res = client.get(f"/{session_id}/sgf")
    assert res.status_code == 200

    data = res.json()
    assert data.keys() == {"sgf"}
    sgf = data["sgf"]
    assert isinstance(sgf, str)
    assert sgf.startswith("(")
    assert ";FF" in sgf
