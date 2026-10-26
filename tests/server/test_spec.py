"""The app serves openapi.yaml, and its routes are the ones the spec lists."""

from __future__ import annotations

import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from fastgtp import GTPTransportManager, create_app
from fastgtp.server.router import SPEC_PATH

# In the spec but not built yet (issues #11 and #12).
NOT_YET_BUILT = {
    "/profiles",
    "/profiles/{profile_name}",
    "/analysis-jobs",
    "/analysis-jobs/{job_id}",
}
METHODS = {"get", "put", "post", "delete", "patch"}


class NoEngine:
    async def open(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    def copy(self) -> NoEngine:
        return self

    async def send_command(self, command: str) -> str:
        raise AssertionError("no engine is needed")


def load_spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_serves_the_spec():
    app = create_app(GTPTransportManager(NoEngine()))
    with TestClient(app) as c:
        res = c.get("/openapi.json")
    assert res.status_code == 200
    assert res.json() == load_spec()


def test_routes_match_the_spec():
    app = create_app(GTPTransportManager(NoEngine()))
    built = {
        (route.path, method.lower())
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    specified = {
        (path, method)
        for path, operations in load_spec()["paths"].items()
        if path not in NOT_YET_BUILT
        for method in operations
        if method in METHODS
    }
    assert built == specified
