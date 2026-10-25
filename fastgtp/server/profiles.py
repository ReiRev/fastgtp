"""Named engine settings that analysis jobs run with.

A profile fixes everything that changes an analysis result: the engine
command, the network, the config file, and the number of visits. Clients pick
a profile by name. To change any of these, publish a profile under a new name
instead of editing an existing one, so a name always means the same settings.

Profiles currently describe KataGo engines, because analysis relies on
KataGo's GTP extensions and command line flags.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_KNOWN_KEYS = frozenset({"command", "model", "config", "visits", "maxTurns"})
_HASH_CHUNK_BYTES = 1 << 20


class ProfileError(ValueError):
    """Raised when the profiles file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Profile:
    """One named set of engine settings."""

    name: str
    command: tuple[str, ...]
    model: Path
    config: Path
    visits: int
    max_turns: int
    model_sha256: str
    config_sha256: str

    @property
    def model_name(self) -> str:
        """Return the network file name without its extensions."""
        name = self.model.name
        for suffix in (".gz", ".bin", ".txt"):
            name = name.removesuffix(suffix)
        return name

    @property
    def overrides(self) -> str:
        """Return the settings fastgtp forces on top of the config file."""
        return _overrides(self.visits)

    def engine_command(self) -> tuple[str, ...]:
        """Return the full command line that starts the engine."""
        return (
            *self.command,
            "-config",
            str(self.config),
            "-model",
            str(self.model),
            "-override-config",
            self.overrides,
        )


def load_profiles(path: str | Path) -> dict[str, Profile]:
    """Read profiles from a TOML file.

    The file holds one ``[profiles."<name>"]`` table per profile with the keys
    ``command``, ``model``, ``config``, ``visits``, and ``maxTurns``.
    Relative paths are resolved against the directory of the file.
    """

    path = Path(path)
    try:
        with path.open("rb") as file:
            document = tomllib.load(file)
    except OSError as exc:
        raise ProfileError(f"Cannot read profiles file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"Invalid TOML in {path}: {exc}") from exc

    tables = document.get("profiles")
    if not isinstance(tables, dict) or not tables:
        raise ProfileError(f"{path} defines no [profiles.<name>] tables")

    base = path.parent
    return {name: _build_profile(name, table, base) for name, table in tables.items()}


def _build_profile(name: str, table: Any, base: Path) -> Profile:
    if not _NAME_PATTERN.fullmatch(name):
        raise ProfileError(
            f"Profile name {name!r} must use lowercase letters, digits, '.', '_' or '-'"
        )
    if not isinstance(table, dict):
        raise ProfileError(f"Profile {name!r} must be a table")
    unknown = set(table) - _KNOWN_KEYS
    if unknown:
        raise ProfileError(f"Profile {name!r} has unknown keys: {sorted(unknown)}")

    command = _command(name, table.get("command"))
    model = _existing_file(name, "model", table.get("model"), base)
    config = _existing_file(name, "config", table.get("config"), base)
    visits = _positive_int(name, "visits", table.get("visits"))
    max_turns = _positive_int(name, "maxTurns", table.get("maxTurns"))

    # The forced overrides and the arguments in the command change results as
    # much as the file does, so they are part of the config hash. The
    # executable path is left out because it differs between machines.
    config_hash = hashlib.sha256(config.read_bytes())
    config_hash.update(b"\n" + _overrides(visits).encode("utf-8"))
    config_hash.update(b"\n" + shlex.join(command[1:]).encode("utf-8"))

    return Profile(
        name=name,
        command=command,
        model=model,
        config=config,
        visits=visits,
        max_turns=max_turns,
        model_sha256=_sha256_file(model),
        config_sha256=config_hash.hexdigest(),
    )


def _overrides(visits: int) -> str:
    return f"maxVisits={visits},reportAnalysisWinratesAs=BLACK"


def _command(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = tuple(shlex.split(value))
    elif isinstance(value, list) and all(isinstance(part, str) for part in value):
        parts = tuple(value)
    else:
        raise ProfileError(f"Profile {name!r} needs 'command' as a string or list")
    if not parts:
        raise ProfileError(f"Profile {name!r} has an empty 'command'")
    return parts


def _existing_file(name: str, key: str, value: Any, base: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ProfileError(f"Profile {name!r} needs '{key}' as a path")
    path = (base / value).resolve()
    if not path.is_file():
        raise ProfileError(f"Profile {name!r}: {key} file {path} does not exist")
    return path


def _positive_int(name: str, key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProfileError(f"Profile {name!r} needs '{key}' as a positive integer")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
