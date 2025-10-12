"""Utilities for working with the Go Text Protocol (GTP).

This module provides helpers to parse GTP commands and responses so they can
be translated to structured REST representations and vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence, TypedDict

_COMMAND_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


class GTPResponsePayload(TypedDict):
    success: bool
    id: str | None
    result: str | None
    error: str | None
    raw: str


@dataclass(slots=True)
class ParsedCommand:
    """Structured representation of a single GTP command line."""

    identifier: str | None
    name: str
    arguments: tuple[str, ...]

    def format(self) -> str:
        """Return the canonical single-line command representation."""
        parts: list[str] = []
        if self.identifier is not None:
            parts.append(self.identifier)
        parts.append(self.name)
        parts.extend(self.arguments)
        return " ".join(parts)


@dataclass(slots=True)
class ParsedResponse:
    """Structured representation of a GTP response."""

    success: bool
    identifier: str | None
    payload: str
    error: str | None
    raw: str

    def as_payload(self) -> GTPResponsePayload:
        """Return a plain dictionary suitable for JSON serialization."""
        return {
            "success": self.success,
            "id": self.identifier,
            "result": self.payload if self.success else None,
            "error": self.error if not self.success else None,
            "raw": self.raw,
        }


def _is_command_name(token: str) -> bool:
    """Best effort detection for canonical GTP command names."""
    return bool(_COMMAND_NAME_PATTERN.fullmatch(token))


def parse_command_line(line: str) -> ParsedCommand:
    """Parse a raw GTP command line into its structured components.

    Parameters
    ----------
    line:
        Raw command line without the terminating newline.

    Returns
    -------
    ParsedCommand
        The structured representation of the given command.

    Raises
    ------
    ValueError
        If the line is empty or cannot be parsed as a GTP command.
    """

    tokens: list[str] = line.strip().split()
    if not tokens:
        raise ValueError("GTP command cannot be empty")

    first = tokens[0]
    if _is_command_name(first):
        identifier: str | None = None
        name = first
        args = tokens[1:]
    else:
        if len(tokens) == 1:
            raise ValueError("GTP command missing name")
        identifier = first
        name = tokens[1]
        args = tokens[2:]

    return ParsedCommand(identifier=identifier, name=name, arguments=tuple(args))


def build_command(
    name: str,
    arguments: Sequence[str] | None = None,
    identifier: str | int | None = None,
) -> str:
    """Format a structured command back into its GTP text representation."""
    args: Iterable[str] = arguments if arguments is not None else ()
    parsed = ParsedCommand(
        identifier=str(identifier) if identifier is not None else None,
        name=name,
        arguments=tuple(str(arg) for arg in args),
    )
    return parsed.format()


def parse_response(raw: str, *, expected_id: str | None = None) -> ParsedResponse:
    """Parse a raw GTP response into a structured representation.

    Parameters
    ----------
    raw:
        The response string exactly as received from the engine.
    expected_id:
        An optional identifier that was part of the original command. When
        provided, it is used to disambiguate between response identifiers and
        payload values on the first line.

    Returns
    -------
    ParsedResponse
        Structured response information.

    Raises
    ------
    ValueError
        If the raw response does not conform to the protocol.
    """

    if not raw:
        raise ValueError("Empty GTP response")

    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    # Drop trailing blank lines that are commonly used as separators in GTP.
    while lines and lines[-1] == "":
        lines.pop()

    if not lines:
        raise ValueError("GTP response missing status line")

    # Skip any leading chatter before the actual GTP status line. Some
    # engines emit informational text prior to the protocol response.
    status_line: str | None = None
    chatter: list[str] = []
    while lines:
        candidate_original = lines.pop(0)
        candidate = candidate_original.lstrip()
        if candidate and candidate[0] in ("=", "?"):
            status_line = candidate
            break
        if candidate_original.strip():
            chatter.append(candidate_original.strip())

    if status_line is None:
        if chatter:
            raise ValueError("GTP response missing status line; got: " + chatter[0])
        raise ValueError("GTP response missing status line")

    status_char = status_line[0]
    if status_char not in ("=", "?"):
        raise ValueError(f"Invalid GTP status prefix: {status_char!r}")

    remainder = status_line[1:].lstrip()
    identifier = expected_id

    if expected_id:
        if remainder.startswith(expected_id):
            remainder = remainder[len(expected_id) :].lstrip()
    else:
        token, sep, rest = remainder.partition(" ")
        has_followup = bool(sep and rest) or bool(lines[1:])
        if token and has_followup and token.isdigit():
            identifier = token
            remainder = rest.lstrip()
        else:
            identifier = None

    payload_lines: list[str] = []
    if remainder:
        payload_lines.append(remainder)
    payload_lines.extend(lines)
    payload_text = "\n".join(payload_lines).strip()

    if status_char == "=":
        return ParsedResponse(
            success=True,
            identifier=identifier,
            payload=payload_text,
            error=None,
            raw=normalized,
        )

    error_message = payload_text or "Unknown error"
    return ParsedResponse(
        success=False,
        identifier=identifier,
        payload="",
        error=error_message,
        raw=normalized,
    )
