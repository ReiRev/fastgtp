import pytest

from fastgtp import create_app, GTPTransportManager, SubprocessGTPTransport
from fastapi.testclient import TestClient


@pytest.fixture(params=["gnugo", "katago"], scope="session")
def gtp_type(request):
    return request.param


@pytest.fixture(scope="session")
def gtp_transport(gtp_type):
    if gtp_type == "gnugo":
        return SubprocessGTPTransport("gnugo --mode gtp")
    elif gtp_type == "katago":
        return SubprocessGTPTransport(
            "katago gtp -config /opt/katago/configs/fastgtp.cfg -model /opt/katago/networks/kata1-b28c512nbt-s11233360640-d5406293331.bin.gz"
        )
    else:
        raise NotImplementedError()


@pytest.fixture(scope="session")
def gtp_transport_manager(gtp_transport):
    return GTPTransportManager(gtp_transport)


@pytest.fixture(scope="session")
def app(gtp_transport_manager):
    return create_app(gtp_transport_manager)


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def session_id(client):
    res = client.post("/open_session")
    res.raise_for_status()
    session_id = res.json()["session_id"]

    yield session_id

    client.post(f"/{session_id}/quit")


@pytest.fixture
def invalid_session_id():
    return "invalid_session_id"
