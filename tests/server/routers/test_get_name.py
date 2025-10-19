from __future__ import annotations


def test_get_name(client, session_id):
    res = client.get(f"/{session_id}/name")
    assert res.status_code == 200

    data = res.json()
    assert "name" in data


def test_get_name_invalid_session(client, invalid_session_id):
    res = client.get(f"/{invalid_session_id}/name")
    assert res.status_code == 404
