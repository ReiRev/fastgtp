import pytest
from httpx import ASGITransport, AsyncClient

from fastgtp import GTPTransport, create_app


class FakeGTPTransport(GTPTransport):
    def __init__(self, responses):
        self._responses = responses
        self.history = []

    async def send_command(self, command: str) -> str:
        self.history.append(command)
        if command not in self._responses:
            raise RuntimeError(f"Unexpected command: {command}")
        return self._responses[command]


@pytest.fixture
def make_app():
    def _factory(responses):
        transport = FakeGTPTransport(responses)
        app = create_app(model_name="hoge", transport=transport)
        return app, transport

    return _factory


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_get_name_returns_gtp_payload(make_app):
    responses = {
        "name": "=KataGo\n\n",
        "version": "=1.0\n\n",
        "protocol_version": "=2\n\n",
    }
    app, transport = make_app(responses)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/hoge/name")

    assert response.status_code == 200
    assert response.json() == {"data": "KataGo"}
    assert transport.history == ["name"]


@pytest.mark.anyio
async def test_get_version_returns_gtp_payload(make_app):
    responses = {
        "name": "=KataGo\n\n",
        "version": "=1.2.3\n\n",
        "protocol_version": "=2\n\n",
    }
    app, transport = make_app(responses)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/hoge/version")

    assert response.status_code == 200
    assert response.json() == {"data": "1.2.3"}
    assert transport.history[-1] == "version"


@pytest.mark.anyio
async def test_get_protocol_version_returns_gtp_payload(make_app):
    responses = {
        "name": "=KataGo\n\n",
        "version": "=1.0\n\n",
        "protocol_version": "=2\n\n",
    }
    app, transport = make_app(responses)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/hoge/protocol_version")

    assert response.status_code == 200
    assert response.json() == {"data": "2"}
    assert transport.history[-1] == "protocol_version"


@pytest.mark.anyio
async def test_gtp_error_maps_to_502(make_app):
    responses = {
        "name": "? engine error\n\n",
        "version": "=1.0\n\n",
        "protocol_version": "=2\n\n",
    }
    app, _ = make_app(responses)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/hoge/name")

    assert response.status_code == 502
    assert "engine error" in response.json()["detail"]
