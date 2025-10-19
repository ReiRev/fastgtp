def test_send_command(client, session_id):
    res = client.post(f"/{session_id}/command", json={"command": "name"})

    assert res.status_code == 200
    assert "detail" in res.json()


def test_send_command_invalid_session(client, invalid_session_id):
    res = client.post(f"/{invalid_session_id}/command", json={"command": "name"})
    assert res.status_code == 404
