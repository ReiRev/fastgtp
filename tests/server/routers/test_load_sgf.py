def test_load_sgf_invalid_session(client, invalid_session_id):
    res = client.post(
        f"/{invalid_session_id}/sgf",
        json={"filename": "/tmp/does-not-exist.sgf"},
    )
    assert res.status_code == 404


def test_load_sgf_requires_filename(client, session_id):
    res = client.post(f"/{session_id}/sgf", json={})
    assert res.status_code == 422
