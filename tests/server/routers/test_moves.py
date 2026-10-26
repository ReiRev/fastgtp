PROBLEMS = "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#"


def new_board(client, session_id):
    res = client.put(f"/sessions/{session_id}/board", json={"size": 9, "komi": 6.5})
    assert res.status_code == 200


def test_play(client, session_id):
    new_board(client, session_id)
    res = client.post(
        f"/sessions/{session_id}/moves", json={"color": "BLACK", "vertex": "E5"}
    )
    assert res.status_code == 201
    assert res.json() == {"color": "BLACK", "vertex": "E5"}
    assert "AB[ee]" in client.get(f"/sessions/{session_id}/board").json()["sgf"]


def test_pass(client, session_id):
    new_board(client, session_id)
    res = client.post(
        f"/sessions/{session_id}/moves", json={"color": "BLACK", "vertex": "PASS"}
    )
    assert res.status_code == 201
    assert res.json()["vertex"] == "PASS"


def test_generate(client, session_id):
    new_board(client, session_id)
    res = client.post(f"/sessions/{session_id}/moves", json={"color": "WHITE"})
    assert res.status_code == 201
    move = res.json()
    assert move["color"] == "WHITE"
    assert move["vertex"]


def test_illegal_move(client, session_id):
    new_board(client, session_id)
    url = f"/sessions/{session_id}/moves"
    client.post(url, json={"color": "BLACK", "vertex": "E5"})
    res = client.post(url, json={"color": "WHITE", "vertex": "E5"})
    assert res.status_code == 409
    body = res.json()
    assert body["type"] == PROBLEMS + "illegal-move"
    assert body["field"] == "vertex"


def test_point_off_the_board(client, session_id):
    new_board(client, session_id)
    res = client.post(
        f"/sessions/{session_id}/moves", json={"color": "BLACK", "vertex": "T19"}
    )
    assert res.status_code == 400
    assert res.json()["type"] == PROBLEMS + "invalid-request"


def test_invalid_vertex(client, session_id):
    res = client.post(
        f"/sessions/{session_id}/moves", json={"color": "BLACK", "vertex": "I5"}
    )
    assert res.status_code == 400
    assert res.json()["field"] == "vertex"


def test_invalid_color(client, session_id):
    res = client.post(f"/sessions/{session_id}/moves", json={"color": "B"})
    assert res.status_code == 400
    assert res.json()["field"] == "color"


def test_undo(client, session_id):
    new_board(client, session_id)
    client.post(
        f"/sessions/{session_id}/moves", json={"color": "BLACK", "vertex": "E5"}
    )
    res = client.delete(f"/sessions/{session_id}/moves/last")
    assert res.status_code == 204
    assert "ee" not in client.get(f"/sessions/{session_id}/board").json()["sgf"]


def test_nothing_to_undo(client, session_id):
    new_board(client, session_id)
    res = client.delete(f"/sessions/{session_id}/moves/last")
    assert res.status_code == 409
    assert res.json()["type"] == PROBLEMS + "no-move-to-undo"


def test_moves_of_unknown_session(client, invalid_session_id):
    url = f"/sessions/{invalid_session_id}/moves"
    assert client.post(url, json={"color": "BLACK"}).status_code == 404
    assert client.delete(url + "/last").status_code == 404
