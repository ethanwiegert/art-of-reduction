#!/usr/bin/env python3
"""Answer the actionable questions from the tool-call log.

    python3 report.py                    # every section
    python3 report.py tools              # calls per tool
    python3 report.py repeats --min 3    # same normalized call, 2+ sessions
    python3 report.py failures           # failure rate per tool
    python3 report.py sessions           # outlier sessions
    python3 report.py import             # drain tool-calls.jsonl into the database

Read-only except for `import`. Stdlib only; no server, no browser.

`repeats` is the section `lazy-automate` consumes: identical work across
sessions is the signal to compile something, and tool counts alone are not.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

AOR_HOME = os.environ.get("AOR_HOME") or os.path.join(
    os.path.expanduser("~"), ".art-of-reduction"
)
DB_PATH = os.path.join(AOR_HOME, "tool-tracking.db")
JSONL_PATH = os.path.join(AOR_HOME, "tool-calls.jsonl")
SAMPLE_CHARS = 160

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s\"']+")
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse the parts of a call that vary run to run, so repeats line up."""
    text = UUID.sub("<uuid>", text)
    text = HOME_PATH.sub("/<home>", text)
    text = NUMBER.sub("<n>", text)
    return WHITESPACE.sub(" ", text).strip()[:SAMPLE_CHARS]


def connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        sys.exit(f"no database at {DB_PATH} - run scripts/install.sh first")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def table(headers, rows) -> str:
    if not rows:
        return "(nothing recorded yet)"
    cells = [[str(c) for c in row] for row in rows]
    widths = [
        max(len(str(headers[i])), *(len(row[i]) for row in cells))
        for i in range(len(headers))
    ]
    lines = ["  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in cells
    )
    return "\n".join(lines)


def total_calls(con) -> int:
    return con.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]


def section_tools(con, limit: int) -> None:
    print("\n== calls per tool ==")
    rows = con.execute(
        "SELECT tool, COUNT(*) AS calls, SUM(status='error') AS errors,"
        "       ROUND(AVG(duration_ms)) AS avg_ms"
        " FROM tool_calls GROUP BY tool ORDER BY calls DESC LIMIT ?",
        (limit,),
    ).fetchall()
    print(
        table(
            ("tool", "calls", "errors", "avg_ms"),
            [(r["tool"], r["calls"], r["errors"], r["avg_ms"] or "-") for r in rows],
        )
    )


def section_failures(con, limit: int) -> None:
    print("\n== failure rate per tool ==")
    rows = con.execute(
        "SELECT tool, COUNT(*) AS calls, SUM(status='error') AS errors,"
        "       ROUND(100.0 * SUM(status='error') / COUNT(*), 1) AS pct"
        " FROM tool_calls GROUP BY tool HAVING errors > 0"
        " ORDER BY pct DESC, errors DESC LIMIT ?",
        (limit,),
    ).fetchall()
    print(
        table(
            ("tool", "calls", "errors", "fail%"),
            [(r["tool"], r["calls"], r["errors"], r["pct"]) for r in rows],
        )
    )


def section_repeats(con, minimum: int, limit: int) -> None:
    print(f"\n== calls repeated across sessions (>= {minimum} total, 2+ sessions) ==")
    buckets = defaultdict(lambda: {"count": 0, "sessions": set(), "sample": ""})
    for row in con.execute(
        "SELECT tool, tool_input, session_id FROM tool_calls WHERE tool_input != ''"
    ):
        key = (row["tool"], normalize(row["tool_input"]))
        bucket = buckets[key]
        bucket["count"] += 1
        bucket["sessions"].add(row["session_id"])
        bucket["sample"] = bucket["sample"] or row["tool_input"][:SAMPLE_CHARS]
    repeats = [
        (tool, data["count"], len(data["sessions"]), data["sample"])
        for (tool, _), data in buckets.items()
        if data["count"] >= minimum and len(data["sessions"]) >= 2
    ]
    repeats.sort(key=lambda item: (-item[2], -item[1], item[0]))
    print(
        table(
            ("tool", "calls", "sessions", "sample input"),
            repeats[:limit],
        )
    )
    if not repeats:
        print("(no cross-session repeats yet)")


def section_sessions(con, limit: int) -> None:
    print("\n== session sizes ==")
    rows = con.execute(
        "SELECT session_id, GROUP_CONCAT(DISTINCT harness) AS harnesses,"
        "       COUNT(*) AS calls, MIN(ts) AS started, SUM(status='error') AS errors"
        " FROM tool_calls WHERE session_id != ''"
        " GROUP BY session_id ORDER BY calls DESC LIMIT ?",
        (limit,),
    ).fetchall()
    counts = sorted((r["calls"] for r in rows), reverse=True)
    median = counts[len(counts) // 2] if counts else 0
    print(
        table(
            ("calls", "errors", "harness", "started", "session"),
            [
                (
                    r["calls"],
                    r["errors"],
                    r["harnesses"],
                    (r["started"] or "")[:19],
                    r["session_id"][:20],
                )
                for r in rows
            ],
        )
    )
    if counts and median and counts[0] >= 3 * median:
        print(
            f"\noutlier: the largest session used {counts[0]} calls, "
            f"{counts[0] / median:.1f}x the median ({median}). "
            "Long sessions are where an agent loops - read its tool trail before "
            "adding more instructions."
        )


def section_import(con) -> None:
    if not os.path.exists(JSONL_PATH):
        print(f"no queue at {JSONL_PATH}")
        return
    rows = []
    with open(JSONL_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    con.executemany(
        "INSERT INTO tool_calls "
        "(ts, session_id, harness, tool, tool_input, tool_output, status, duration_ms) "
        "VALUES (:ts, :session_id, :harness, :tool, :tool_input, :tool_output, :status,"
        " :duration_ms)",
        rows,
    )
    con.commit()
    os.remove(JSONL_PATH)
    print(f"imported {len(rows)} queued calls into {DB_PATH}")


def main(argv: list) -> None:
    command = argv[0] if argv else "all"
    minimum, limit = 3, 20
    if "--min" in argv:
        minimum = int(argv[argv.index("--min") + 1])
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    con = connect()
    if command == "import":
        section_import(con)
        return
    print(f"{DB_PATH}: {total_calls(con)} calls recorded")
    sections = {"tools": section_tools, "failures": section_failures, "sessions": section_sessions}
    if command == "repeats":
        section_repeats(con, minimum, limit)
    elif command in sections:
        sections[command](con, limit)
    elif command in {"all", "--help", "-h"}:
        for name in ("tools", "failures", "sessions"):
            sections[name](con, limit)
        section_repeats(con, minimum, limit)
    else:
        sys.exit(f"unknown section: {command}")
    con.close()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except sqlite3.Error as exc:
        sys.exit(f"sqlite error: {exc}")
