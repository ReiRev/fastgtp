"""Turning the analysis extension on from its settings file."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fastgtp import GTPTransportManager, create_app
from fastgtp.katago.config import load_settings
from fastgtp.katago.router import SPEC as EXTENSION_SPEC
from fastgtp.katago.router import create_katago_router
from fastgtp.server.router import SPEC, merge_specs
from tests.server.test_spec import NoEngine

FAKE = Path(__file__).with_name("fake_analysis.py")


def write_settings(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "katago.toml"
    path.write_text(body)
    return path


def fake_settings(tmp_path: Path, command: str | None = None) -> Path:
    command = command or f'["{sys.executable}", "{FAKE}"]'
    return write_settings(
        tmp_path,
        f"""
[katago.default]
command = {command}
configs = ["a.cfg"]
model = "m.bin.gz"
max_visits = 100
""",
    )


def app_with_extension(settings_path: Path):
    router = create_katago_router(load_settings(settings_path))
    return create_app(GTPTransportManager(NoEngine()), katago_router=router)


def test_settings_are_read(tmp_path):
    settings = load_settings(fake_settings(tmp_path))
    assert list(settings) == ["default"]
    assert settings["default"].max_visits == 100
    assert settings["default"].max_running == 1


def test_example_is_valid():
    example = Path(__file__).parents[2] / "examples" / "katago.toml"
    settings = load_settings(example)
    assert list(settings) == ["default"]
    assert settings["default"].override_strings() == {
        "numSearchThreadsPerAnalysisThread": "8"
    }


def test_overrides_may_be_numbers_or_booleans(tmp_path):
    body = '[katago.a]\ncommand = ["k"]\nconfigs = ["c"]\nmodel = "m"\n'
    body += "overrides = { maxVisits = 10, nnRandomize = false, x = 0.5 }"
    settings = load_settings(write_settings(tmp_path, body))["a"]
    assert settings.override_strings() == {
        "maxVisits": "10",
        "nnRandomize": "false",
        "x": "0.5",
    }


@pytest.mark.parametrize(
    "body",
    [
        "[katago]",
        '[katago."a/b"]\ncommand = ["k"]\nconfigs = ["c"]\nmodel = "m"',
        '[katago.a]\ncommand = ["k"]\nconfigs = ["c"]\nmodel = "m"\nmaxVisits = 1',
        '[katago.a]\ncommand = ["k"]\nconfigs = []\nmodel = "m"',
        '[katago.a]\ncommand = [""]\nconfigs = ["c"]\nmodel = "m"',
        '[katago.a]\ncommand = ["k"]\nconfigs = ["c"]\nmodel = "m"\nmax_running = true',
        '[katago.a]\ncommand = ["k"]\nconfigs = ["c"]\nmodel = "m"\ntimeout_seconds = inf',
    ],
    ids=["none", "bad-name", "unknown-key", "no-config", "empty", "bool", "inf"],
)
def test_bad_settings_are_refused(tmp_path, body):
    with pytest.raises(ValidationError):
        load_settings(write_settings(tmp_path, body))


def test_extension_routes_and_spec(tmp_path):
    app = app_with_extension(fake_settings(tmp_path))
    with TestClient(app) as c:
        assert c.get("/katago").json() == {"items": [{"id": "default"}]}
        assert c.get("/katago/default/version").json()["version"] == "1.0.0"
        spec = c.get("/openapi.json").json()

    extension = yaml.safe_load(EXTENSION_SPEC.read_text("utf-8"))
    assert set(extension["paths"]) <= set(spec["paths"])
    built = {
        (route.path, method.lower())
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    specified = {
        (path, method)
        for path, operations in spec["paths"].items()
        for method in operations
        if method in {"get", "put", "post", "delete", "patch"}
    }
    assert built == specified


def test_engine_that_does_not_start_stops_the_app(tmp_path):
    good = load_settings(fake_settings(tmp_path))["default"]
    bad = good.model_copy(update={"command": ["/nonexistent/katago"]})
    router = create_katago_router({"good": good, "bad": bad})
    app = create_app(GTPTransportManager(NoEngine()), katago_router=router)
    with pytest.raises(OSError):
        with TestClient(app):
            pass
    # The KataGo that had started was stopped.
    process = router.katagos["good"].engine._process
    assert process is None


def test_conflicting_components_are_refused():
    spec = yaml.safe_load(SPEC.read_text("utf-8"))
    name, schema = next(iter(spec["components"]["schemas"].items()))
    clash = {"components": {"schemas": {name: {**schema, "title": "other"}}}}
    with pytest.raises(ValueError):
        merge_specs(spec, clash)
    with pytest.raises(ValueError):
        merge_specs(spec, {"paths": {"/sessions": {}}})
    # The same content under the same name is fine.
    same = {"components": {"schemas": {name: schema}}}
    assert merge_specs(spec, same)["components"] == spec["components"]


def test_main_reads_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTGTP_ENGINE", "gnugo --mode gtp")
    monkeypatch.setenv("FASTGTP_KATAGO_CONFIG", str(fake_settings(tmp_path)))
    sys.modules.pop("fastgtp.server.main", None)
    main = importlib.import_module("fastgtp.server.main")
    try:
        paths = {route.path for route in main.app.routes}
        assert "/katago/{katago_id}/queries" in paths
    finally:
        sys.modules.pop("fastgtp.server.main", None)
