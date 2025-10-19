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
