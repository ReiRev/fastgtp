def test_get_sgf(client, session_id):
    res = client.get(f"/{session_id}/sgf")
    assert res.status_code == 200

    data = res.json()
    assert data.keys() == {"sgf"}

    sgf = data["sgf"]
    assert isinstance(sgf, str)


def test_get_sgf_invalid_session(client, invalid_session_id):
    res = client.get(f"/{invalid_session_id}/sgf")
    assert res.status_code == 404
