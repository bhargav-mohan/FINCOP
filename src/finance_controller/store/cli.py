from __future__ import annotations

import argparse
import json
import sys

from finance_controller.store.notes import add_note, resolve_exception
from finance_controller.store.runs import recent_runs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local SQLite store for review history and notes.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    note = sub.add_parser("note")
    note.add_argument("--batch-key", required=True)
    note.add_argument("--exception-key", required=True)
    note.add_argument("--author", default="analyst")
    note.add_argument("--note", default="")
    note.add_argument("--assignee", default="")

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--batch-key", required=True)
    resolve.add_argument("--exception-key", required=True)
    resolve.add_argument("--author", default="analyst")
    resolve.add_argument("--note", default="")
    resolve.add_argument("--assignee", default="")

    history = sub.add_parser("history")
    history.add_argument("--batch-key", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "note":
        add_note(
            batch_key=args.batch_key,
            exception_key=args.exception_key,
            author=args.author,
            note=args.note,
            assignee=args.assignee,
        )
        json.dump({"ok": True}, sys.stdout)
        return
    if args.cmd == "resolve":
        resolve_exception(
            batch_key=args.batch_key,
            exception_key=args.exception_key,
            author=args.author,
            note=args.note,
            assignee=args.assignee,
        )
        json.dump({"ok": True}, sys.stdout)
        return
    json.dump({"runs": recent_runs(args.batch_key)}, sys.stdout)


if __name__ == "__main__":
    main()
