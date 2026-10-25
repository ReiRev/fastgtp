"""A small GTP engine that answers the commands analysis needs.

It stands in for KataGo so the analysis tests run without a GPU. The win rate
it reports is a function of the number of moves played and the side to move,
so tests can check which position each result belongs to:

    winrate = 0.5 + 0.01 * moves_played + (0.001 if white to move else 0)

Flags before the KataGo-style arguments change its behavior for a test.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

ALL_COMMANDS = [
    "protocol_version",
    "name",
    "version",
    "list_commands",
    "quit",
    "boardsize",
    "rectangular_boardsize",
    "clear_board",
    "komi",
    "play",
    "kata-set-rules",
    "set_position",
    "kata-search_analyze",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--without", action="append", default=[])
    parser.add_argument("--analyze-seconds", type=float, default=0.0)
    parser.add_argument("--exit-on-analyze", type=int, default=0)
    parser.add_argument("--stderr-bytes", type=int, default=0)
    parser.add_argument("--ignore-sigterm", action="store_true")
    parser.add_argument("--exit-after-play", type=int, default=0)
    parser.add_argument("--close-stdout-on-analyze", action="store_true")
    parser.add_argument("--no-root-info", action="store_true")
    parser.add_argument("--hang-on")
    parser.add_argument("--reject-setup", action="store_true")
    parser.add_argument("--info-bytes", type=int, default=0)
    parser.add_argument("--log")
    args, engine_args = parser.parse_known_args()

    if args.ignore_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    log = open(args.log, "a", encoding="utf-8") if args.log else None
    if log:
        log.write(f"pid {os.getpid()}\n")
        log.write("argv " + " ".join(engine_args) + "\n")
        log.flush()
    if args.stderr_bytes:
        sys.stderr.write("x" * args.stderr_bytes + "\n")
        sys.stderr.flush()

    commands = [name for name in ALL_COMMANDS if name not in args.without]
    stones: dict[str, str] = {}
    moves_played = 0
    analyses = 0

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if log:
            log.write(line + "\n")
            log.flush()
        name, *rest = line.split()

        if name == args.hang_on:
            while True:
                time.sleep(1)
        if name not in commands:
            reply(False, "unknown command")
        elif name == "quit":
            reply(True)
            return
        elif name == "name":
            reply(True, "FakeEngine")
        elif name == "version":
            reply(True, "0.1")
        elif name == "list_commands":
            reply(True, "\n".join(commands))
        elif name in ("boardsize", "rectangular_boardsize", "clear_board"):
            stones.clear()
            moves_played = 0
            reply(True)
        elif name == "set_position" and args.reject_setup:
            reply(False, "illegal position")
        elif name == "set_position":
            stones = dict(zip(rest[1::2], rest[0::2]))
            reply(True)
        elif name == "play":
            color, point = rest
            if point != "pass" and point in stones:
                reply(False, "illegal move")
                continue
            if point != "pass":
                stones[point] = color
            moves_played += 1
            reply(True)
            if args.exit_after_play and moves_played >= args.exit_after_play:
                sys.exit(0)
        elif name == "kata-search_analyze":
            analyses += 1
            if args.exit_on_analyze and analyses >= args.exit_on_analyze:
                sys.stderr.write("fake engine crashed on purpose\n")
                sys.stderr.flush()
                sys.exit(3)
            if args.close_stdout_on_analyze:
                sys.stdout.close()
                while True:
                    time.sleep(1)
            time.sleep(args.analyze_seconds)
            if args.no_root_info:
                reply(True, "info move D4 visits 10 winrate 0.123456 order 0 pv D4")
                continue
            winrate = 0.5 + 0.01 * moves_played + (0.001 if rest[0] == "W" else 0.0)
            # KataGo prints the moves and rootInfo on one line.
            reply(
                True,
                "info move D4 visits 10 winrate 0.123456 order 0 pv D4 "
                + "info move C3 pv C3 " * (args.info_bytes // 19)
                + f"rootInfo visits 10 utility 0.0 winrate {winrate:.6f} scoreLead 0.5",
            )
        else:
            reply(True)

    # Like an engine stuck in a search, it outlives its closed stdin and only
    # SIGKILL stops it.
    while args.ignore_sigterm:
        time.sleep(1)


def reply(success: bool, payload: str = "") -> None:
    prefix = "=" if success else "?"
    sys.stdout.write(f"{prefix} {payload}\n\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
