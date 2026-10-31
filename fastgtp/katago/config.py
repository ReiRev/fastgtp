"""The KataGo extension's settings, read from a TOML file.

Each ``[katago.<name>]`` table is one ``katago analysis`` process, served
under ``/katago/<name>``::

    [katago.default]
    command = ["katago"]
    configs = ["analysis.cfg"]
    model = "model.bin.gz"
    max_visits = 10000
    overrides = { numSearchThreads = 8 }

``overrides`` are passed to KataGo with ``-override-config``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictInt,
    StringConstraints,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# The name goes into URLs, so it is kept to characters that need no escaping.
KataGoName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class KataGoSettings(BaseModel):
    """How to start one KataGo, and the limits on its queries."""

    model_config = ConfigDict(extra="forbid")

    command: list[NonEmpty] = Field(min_length=1)
    configs: list[NonEmpty] = Field(min_length=1)
    model: NonEmpty
    human_model: NonEmpty | None = None
    overrides: dict[NonEmpty, str | bool | StrictInt | FiniteFloat] = {}
    max_running: StrictInt = Field(1, ge=1)
    max_queued: StrictInt = Field(64, ge=0)
    timeout_seconds: FiniteFloat = Field(600.0, gt=0)
    keep_seconds: FiniteFloat = Field(600.0, gt=0)
    max_visits: StrictInt | None = Field(None, ge=1)

    def override_strings(self) -> dict[str, str]:
        """The overrides as KataGo reads them on its command line."""
        return {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in self.overrides.items()
        }


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    katago: dict[KataGoName, KataGoSettings] = Field(min_length=1)


def load_settings(path: str | Path) -> dict[str, KataGoSettings]:
    """Read the KataGo settings in ``path``, keyed by name."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _File.model_validate(data).katago
