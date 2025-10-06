import pytest

from fastgtp.gtp import build_command, parse_command_line, parse_response


def test_parse_command_line_without_identifier():
    parsed = parse_command_line("protocol_version")
    assert parsed.identifier is None
    assert parsed.name == "protocol_version"
    assert parsed.arguments == ()


def test_parse_command_line_with_identifier():
    parsed = parse_command_line("42 genmove B")
    assert parsed.identifier == "42"
    assert parsed.name == "genmove"
    assert parsed.arguments == ("B",)


def test_build_command_roundtrip():
    command = build_command("play", ["B", "D4"], identifier="7")
    assert command == "7 play B D4"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=\n\n", (True, None, "")),
        ("=5\nD4\n\n", (True, "5", "D4")),
        ("=\nwhite\nblack\n\n", (True, None, "white\nblack")),
    ],
)
def test_parse_response_success(raw, expected):
    success, identifier, payload = expected
    parsed = parse_response(raw, expected_id=identifier)
    assert parsed.success is success
    assert parsed.identifier == identifier
    assert parsed.payload == payload
    assert parsed.error is None


def test_parse_error_response_without_expected_id():
    parsed = parse_response("? load error\n\n")
    assert parsed.success is False
    assert parsed.error == "load error"
    assert parsed.payload == ""


def test_parse_response_invalid_prefix():
    with pytest.raises(ValueError):
        parse_response("invalid\n\n")


def test_parse_response_skips_engine_chatter():
    raw = "Engine starting...\n=\nhello\n\n"
    parsed = parse_response(raw)
    assert parsed.success is True
    assert parsed.payload == "hello"


def test_parse_response_allows_leading_whitespace():
    raw = "   = 42\nvalue\n\n"
    parsed = parse_response(raw)
    assert parsed.success is True
    assert parsed.identifier is None
    assert parsed.payload == "42\nvalue"


def test_parse_response_missing_status_reports_chatter():
    with pytest.raises(ValueError) as excinfo:
        parse_response("Error: network missing\n\n")
    assert "network missing" in str(excinfo.value)
