def test_get_protocol_version(client, session_id):
    res = client.get(f"/{session_id}/protocol_version")
    assert res.status_code == 200

    data = res.json()
    assert "protocol_version" in data


def test_get_protocol_version_invalid_session(client, invalid_session_id):
    res = client.get(f"/{invalid_session_id}/protocol_version")
    assert res.status_code == 404
