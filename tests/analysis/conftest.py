from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from fastgtp import (
    AnalysisService,
    GTPTransportManager,
    JobSettings,
    SubprocessGTPTransport,
    create_app,
    load_profiles,
)

from .helpers import fake_engine_command


@pytest.fixture
def engine_log(tmp_path: Path) -> Path:
    return tmp_path / "engine.log"


@pytest.fixture
def write_profiles(tmp_path: Path) -> Callable[..., Path]:
    """Write a profiles file whose profiles run the fake engine."""

    (tmp_path / "model.bin.gz").write_bytes(b"fake network")
    (tmp_path / "analysis.cfg").write_text("numSearchThreads = 1\n")

    def write(
        profiles: dict[str, list[str]], *, visits: int = 50, max_turns: int = 10
    ) -> Path:
        lines = []
        for name, flags in profiles.items():
            command = ", ".join(f'"{part}"' for part in fake_engine_command(*flags))
            lines += [
                f'[profiles."{name}"]',
                f"command = [{command}]",
                'model = "model.bin.gz"',
                'config = "analysis.cfg"',
                f"visits = {visits}",
                f"maxTurns = {max_turns}",
                "",
            ]
        path = tmp_path / "profiles.toml"
        path.write_text("\n".join(lines))
        return path

    return write


@pytest.fixture
def make_client(write_profiles) -> Iterator[Callable[..., TestClient]]:
    """Start an app with the given profiles and job settings."""

    clients: list[TestClient] = []

    def make(
        profiles: dict[str, list[str]] | None = None,
        *,
        with_gtp: bool = False,
        root_path: str = "",
        max_turns: int = 10,
        **settings,
    ) -> TestClient:
        path = write_profiles(profiles or {"test-v1": []}, max_turns=max_turns)
        service = AnalysisService(load_profiles(path), JobSettings(**settings))
        manager = (
            GTPTransportManager(SubprocessGTPTransport(fake_engine_command()))
            if with_gtp
            else None
        )
        client = TestClient(create_app(manager, analysis=service), root_path=root_path)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
