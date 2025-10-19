def test_clear_board(client, session_id):
    res = client.post(f"/{session_id}/clear_board")
    assert res.status_code == 200

    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


def test_clear_board_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/clear_board")
    assert res.status_code == 404
