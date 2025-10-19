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
