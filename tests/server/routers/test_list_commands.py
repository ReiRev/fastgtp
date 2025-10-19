def test_list_commands(client, session_id):
    res = client.get(f"/{session_id}/commands")
    assert res.status_code == 200

    data = res.json()
    assert "commands" in data

    commands = data["commands"]
    assert isinstance(commands, list)

    expected_subset = {"protocol_version", "name", "version", "list_commands", "quit"}
    assert expected_subset.issubset(set(commands))
