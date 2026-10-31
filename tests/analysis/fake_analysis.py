"""A fake ``katago analysis`` for tests.

It speaks KataGo's JSON lines without a model or a GPU. Parts of a query make
it behave the way KataGo does:

- a move to ``Z99`` is an error, like any point KataGo cannot read;
- an unknown field ``unknownField`` is a warning, and the query still runs;
- ``maxVisits`` of 1000000 or more keeps every turn searching until the query
  is terminated.
"""

from __future__ import annotations

import argparse
import json
import sys

MODEL = {
    "name": "/models/fake.bin.gz",
    "internalName": "fake",
    "maxBatchSize": 8,
    "usesHumanSLProfile": False,
    "version": 15,
    "usingFP16": "false",
}


def write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def response(query_id: str, turn: int, visits: int) -> dict:
    return {
        "id": query_id,
        "turnNumber": turn,
        "isDuringSearch": False,
        # Black moves first, as in a game without handicap stones.
        "rootInfo": {
            "currentPlayer": "B" if turn % 2 == 0 else "W",
            "visits": visits,
            "winrate": 0.5,
            "scoreLead": 0.0,
        },
        "moveInfos": [],
    }


def main() -> None:
    # KataGo's single-dash flags, such as -human-model, would otherwise be
    # read as -h.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--argv-file")
    parser.add_argument("--exit-after-queries", type=int, default=0)
    # Ignore terminate, as a stuck KataGo would. Other input is still read.
    parser.add_argument("--ignore-terminate", action="store_true")
    args, rest = parser.parse_known_args()
    if args.argv_file:
        with open(args.argv_file, "w") as f:
            json.dump(rest, f)

    # Turns of queries that search until terminated, by query id.
    searching: dict[str, list[int]] = {}
    queries = 0
    for line in sys.stdin:
        message = json.loads(line)
        query_id = message["id"]
        action = message.get("action")
        if action == "query_version":
            write({**message, "version": "1.0.0", "git_hash": "fake"})
        elif action == "query_models":
            write({**message, "models": [MODEL]})
        elif action == "terminate" and args.ignore_terminate:
            continue
        elif action == "terminate":
            write(message)
            turns = searching.pop(message["terminateId"], [])
            # Like KataGo, the turn being searched reports what it found, and
            # turns not started report noResults.
            for i, turn in enumerate(turns):
                if i == 0:
                    write(response(message["terminateId"], turn, 1))
                else:
                    write(
                        {
                            "id": message["terminateId"],
                            "turnNumber": turn,
                            "isDuringSearch": False,
                            "noResults": True,
                        }
                    )
        else:
            queries += 1
            if args.exit_after_queries and queries >= args.exit_after_queries:
                sys.exit(1)
            if any(move[1] == "Z99" for move in message.get("moves", [])):
                write(
                    {
                        "id": query_id,
                        "field": "moves",
                        "error": "Could not parse board location: Z99",
                    }
                )
                continue
            if "unknownField" in message:
                write(
                    {
                        "id": query_id,
                        "field": "unknownField",
                        "warning": "Unexpected or unused field",
                    }
                )
            turns = sorted(
                set(message.get("analyzeTurns", [len(message.get("moves", []))]))
            )
            if message.get("maxVisits", 0) >= 1_000_000:
                searching[query_id] = turns
                continue
            for turn in turns:
                write(response(query_id, turn, message.get("maxVisits", 10)))


if __name__ == "__main__":
    main()
