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
