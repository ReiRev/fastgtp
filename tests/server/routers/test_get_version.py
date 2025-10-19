def test_get_version(client, session_id):
    res = client.get(f"/{session_id}/version")
    assert res.status_code == 200

    data = res.json()
    assert "version" in data


def test_get_version_invalid_session(client, invalid_session_id):
    res = client.get(f"/{invalid_session_id}/version")
    assert res.status_code == 404
