"""The KataGo extension's settings, read from a TOML file.

Each ``[katago.<name>]`` table is one ``katago analysis`` process, served
under ``/katago/<name>``::

    [katago.default]
    command = ["katago"]
    configs = ["analysis.cfg"]
    model = "model.bin.gz"
    max_visits = 10000
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# The name goes into URLs, so it is kept to characters that need no escaping.
KataGoName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]


class KataGoSettings(BaseModel):
    """How to start one KataGo, and the limits on its queries."""

    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    configs: list[str] = Field(min_length=1)
    model: str
    human_model: str | None = None
    overrides: dict[str, str] = {}
    max_running: int = Field(1, ge=1)
    max_queued: int = Field(64, ge=0)
    timeout_seconds: float = Field(600.0, gt=0)
    keep_seconds: float = Field(600.0, gt=0)
    max_visits: int | None = Field(None, ge=1)


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    katago: dict[KataGoName, KataGoSettings] = Field(min_length=1)


def load_settings(path: str | Path) -> dict[str, KataGoSettings]:
    """Read the KataGo settings in ``path``, keyed by name."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _File.model_validate(data).katago
