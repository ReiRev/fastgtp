"""A minimal GTP engine for transport tests.

It answers every command with success. Flags make it misbehave the way real
engines can, so the tests need no Go engine.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stderr-bytes", type=int, default=0)
    parser.add_argument("--ignore-sigterm", action="store_true")
    parser.add_argument("--exit-after", type=int, default=0)
    parser.add_argument("--line-bytes", type=int, default=0)
    args = parser.parse_args()

    if args.ignore_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    answered = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        if args.stderr_bytes:
            # Written before the reply, so an unread stderr pipe blocks the
            # engine before it can answer.
            sys.stderr.write("x" * args.stderr_bytes + "\n")
            sys.stderr.flush()
        payload = "y" * args.line_bytes if args.line_bytes else "ok"
        sys.stdout.write(f"= {payload}\n\n")
        sys.stdout.flush()
        answered += 1
        if args.exit_after and answered >= args.exit_after:
            return

    # Like an engine stuck in a search, it outlives its closed stdin and only
    # SIGKILL stops it.
    while args.ignore_sigterm:
        time.sleep(1)


if __name__ == "__main__":
    main()
