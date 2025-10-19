def test_get_komi(client, session_id):
    res = client.get(f"/{session_id}/komi")
    assert res.status_code == 200

    data = res.json()
    assert data.keys() == {"komi"}
    assert isinstance(data["komi"], (int, float))


def test_get_komi_invalid_session(client, invalid_session_id):
    res = client.get(f"/{invalid_session_id}/komi")
    assert res.status_code == 404
