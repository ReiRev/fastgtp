PROBLEMS = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"


def test_empty_board(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"size": 9, "komi": 5.5})
    assert res.status_code == 200
    board = res.json()
    assert board["size"] == 9
    assert board["komi"] == 5.5
    assert "SZ[9]" in board["sgf"]

    assert client.get(f"/sessions/{session_id}/board").json() == board


def test_board_from_sgf(client, session_id):
    sgf = "(;GM[1]SZ[9]KM[6.5];B[ee];W[cc];B[gg])"
    res = client.put(f"/sessions/{session_id}/board", json={"sgf": sgf})
    assert res.status_code == 200
    board = res.json()
    assert board["size"] == 9
    assert board["komi"] == 6.5


def test_board_from_sgf_with_move_count(client, session_id):
    sgf = "(;GM[1]SZ[9]KM[6.5];B[ee];W[cc];B[gg])"
    res = client.put(
        f"/sessions/{session_id}/board", json={"sgf": sgf, "move_count": 1}
    )
    assert res.status_code == 200
    # Only the first move is on the board.
    position = res.json()["sgf"]
    assert "ee" in position
    assert "cc" not in position


def test_size_the_engine_rejects(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"size": 25, "komi": 0})
    assert res.status_code == 400
    body = res.json()
    assert body["type"] == PROBLEMS + "invalid-request"
    assert body["field"] == "size"


def test_unreadable_sgf(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"sgf": "(;SZ[99])"})
    assert res.status_code == 400
    body = res.json()
    assert body["type"] == PROBLEMS + "invalid-request"
    assert body["field"] == "sgf"
    assert "/tmp" not in res.text


def test_both_kinds_of_board(client, session_id):
    res = client.put(
        f"/sessions/{session_id}/board",
        json={"size": 9, "komi": 6.5, "sgf": "(;SZ[9])"},
    )
    assert res.status_code == 400


def test_neither_kind_of_board(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"size": 9})
    assert res.status_code == 400


def test_move_count_without_sgf(client, session_id):
    res = client.put(
        f"/sessions/{session_id}/board",
        json={"size": 9, "komi": 6.5, "move_count": 1},
    )
    assert res.status_code == 400


def test_size_out_of_range(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"size": 1, "komi": 0})
    assert res.status_code == 400
    assert res.json()["field"] == "size"


def test_board_of_unknown_session(client, invalid_session_id):
    res = client.get(f"/sessions/{invalid_session_id}/board")
    assert res.status_code == 404
    res = client.put(
        f"/sessions/{invalid_session_id}/board", json={"size": 9, "komi": 0}
    )
    assert res.status_code == 404


def test_komi_must_be_a_number(client, session_id):
    res = client.put(
        f"/sessions/{session_id}/board",
        content='{"size": 9, "komi": NaN}',
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json()["field"] == "komi"


def test_sgf_that_stops_the_engine(client, gtp_type, session_id):
    # GNU Go exits on SGF it cannot parse. The session stays and the next
    # call starts a new engine.
    res = client.put(f"/sessions/{session_id}/board", json={"sgf": "garbage"})
    assert res.status_code == (500 if gtp_type == "gnugo" else 400)
    assert client.get(f"/sessions/{session_id}/board").status_code == 200
