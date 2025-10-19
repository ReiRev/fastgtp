def test_set_komi(client, session_id):
    komi = 10

    res = client.post(f"/{session_id}/komi", json={"value": komi})
    assert res.status_code == 200
    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)

    res = client.get(f"/{session_id}/komi")
    assert res.json()["komi"] == komi


def test_set_komi_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/komi", json={"value": 6.5})
    assert res.status_code == 404
