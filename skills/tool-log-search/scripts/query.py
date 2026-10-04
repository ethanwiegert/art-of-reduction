#!/usr/bin/env python3
"""Search the tool-call log and print JSON Lines an agent can parse.

    python3 query.py search [filters]      # matching calls, newest first
    python3 query.py trail <session_id>    # one session's calls, in order
    python3 query.py sql "SELECT ..."      # any read-only query
    python3 query.py schema                # columns and tool kinds

Filters for `search`:
    --tool X        a kind (shell, read, edit, search, web) or a raw tool name
    --session ID    --harness NAME    --status success|error|unknown
    --since TS      --until TS        ISO-8601 UTC prefixes, e.g. 2026-10-01
    --grep TEXT     case-insensitive substring of tool_input or tool_output
    --limit N       default 50 (0 = all)

    --chars N       truncate tool_input/tool_output per row (default 300, 0 = all)

One JSON object per line, so `head`, `grep` and `jq` work on it and a model
reads only the rows it asked for. The database is opened read-only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tool-tracking", "scripts")
)
from report import DB_PATH, KINDS, kind  # noqa: E402

COLUMNS = "id, ts, session_id, harness, tool, kind(tool) AS kind, status, duration_ms, tool_input, tool_output"
FILTERS = {
    "--tool": "(kind(tool) = lower(:tool) OR lower(tool) = lower(:tool))",
    "--session": "session_id = :session",
    "--harness": "harness = :harness",
    "--status": "status = :status",
    "--since": "ts >= :since",
    "--until": "ts < :until",
    "--grep": "instr(lower(tool_input || ' ' || tool_output), lower(:grep)) > 0",
}


def connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        sys.exit(f"no database at {DB_PATH} - set AOR_HOME or run tool-tracking's install.sh")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.create_function("kind", 1, kind, deterministic=True)
    return con


def emit(rows, chars: int) -> int:
    count = 0
    for row in rows:
        record = dict(row)
        for field in ("tool_input", "tool_output"):
            value = record.get(field)
            if chars and isinstance(value, str) and len(value) > chars:
                record[field] = value[:chars] + f"...[+{len(value) - chars}]"
        print(json.dumps(record, ensure_ascii=False))
        count += 1
    return count


def parse(argv: list) -> tuple:
    options = {"--limit": "50", "--chars": "300"}
    positional = []
    queue = list(argv)
    while queue:
        arg = queue.pop(0)
        if arg in FILTERS or arg in options:
            if not queue:
                sys.exit(f"{arg} needs a value")
            options[arg] = queue.pop(0)
        elif arg.startswith("--"):
            sys.exit(f"unknown option: {arg}")
        else:
            positional.append(arg)
    for name in ("--limit", "--chars"):
        try:
            options[name] = max(0, int(options[name]))
        except ValueError:
            sys.exit(f"{name} needs an integer")
    return positional, options


def search(con, options) -> int:
    used = [flag for flag in FILTERS if flag in options]
    where = " AND ".join(FILTERS[flag] for flag in used) or "1"
    params = {flag[2:]: options[flag] for flag in used}
    return emit(con.execute(
        f"SELECT {COLUMNS} FROM tool_calls WHERE {where}"
        " ORDER BY ts DESC, id DESC LIMIT :limit",
        {**params, "limit": options["--limit"] or -1}), options["--chars"])


def main(argv: list) -> None:
    positional, options = parse(argv)
    command = positional[0] if positional else "--help"
    if command in {"--help", "-h", "help"}:
        print(__doc__.strip())
        return
    if command == "schema":
        print(json.dumps({
            "db": DB_PATH,
            "table": "tool_calls",
            "columns": ["id", "ts", "session_id", "harness", "tool", "tool_input",
                        "tool_output", "status", "duration_ms"],
            "kinds": sorted(set(KINDS.values())),
            "sql_function": "kind(tool) folds harness tool names into kinds",
        }))
        return
    con = connect()
    if command == "search":
        count = search(con, options)
    elif command == "trail" and len(positional) == 2:
        count = emit(con.execute(
            f"SELECT {COLUMNS} FROM tool_calls WHERE session_id = ? ORDER BY ts, id",
            (positional[1],)), options["--chars"])
    elif command == "sql" and len(positional) == 2:
        count = emit(con.execute(positional[1]), options["--chars"])
    else:
        sys.exit(f"usage: query.py search|trail <session>|sql <query>|schema  (got {' '.join(positional)})")
    if not count:
        print("(no rows)", file=sys.stderr)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except sqlite3.Error as exc:
        sys.exit(f"sqlite error: {exc}")
