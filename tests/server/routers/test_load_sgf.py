import pytest

from fastgtp.server import router as router_module


@pytest.fixture
def content():
    return "(;B[hh](;W[ii])(;W[hi]C[h]))"


@pytest.mark.parametrize(
    "move",
    [
        None,
        1,
        2,
    ],
)
def test_load_sgf(client, session_id, content, move):
    res = client.post(
        f"/{session_id}/sgf",
        json={
            "content": content,
            "move": move,
        },
    )
    res.status_code == 200


def test_load_sgf_invalid_session(client, invalid_session_id, content):
    res = client.post(
        f"/{invalid_session_id}/sgf",
        json={"content": content},
    )
    assert res.status_code == 404


def test_load_sgf_inline_invalid_session(client, invalid_session_id, content):
    res = client.post(
        f"/{invalid_session_id}/sgf",
        json={"content": content},
    )
    assert res.status_code == 404
