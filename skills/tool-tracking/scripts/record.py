#!/usr/bin/env python3
"""Append one tool call to the art-of-reduction log.

A harness runs this as a post-tool hook: it pipes its own JSON payload to stdin,
this script maps that harness's field names onto the shared `tool_calls` schema
and writes one row.

    python3 record.py --harness hermes      # payload on stdin

Contract (keep it): always exit 0 and always print `{}` on stdout. A hook that
errors must not break or slow the agent loop; diagnostics go to stderr, which
harnesses log and ignore.

Environment overrides:
    AOR_HOME         store directory (default ~/.art-of-reduction)
    AOR_TRUNCATE     max characters kept per input/output field (default 2000)
    AOR_RECORD_MODE  'sqlite' (default) or 'jsonl' to append a line instead of
                     inserting; drain later with `report.py import`
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

AOR_HOME = os.environ.get("AOR_HOME") or os.path.join(
    os.path.expanduser("~"), ".art-of-reduction"
)
DB_PATH = os.path.join(AOR_HOME, "tool-tracking.db")
JSONL_PATH = os.path.join(AOR_HOME, "tool-calls.jsonl")
RECORD_MODE = (os.environ.get("AOR_RECORD_MODE") or "sqlite").strip().lower()
try:
    TRUNCATE = max(0, int(os.environ.get("AOR_TRUNCATE") or 2000))
except ValueError:
    TRUNCATE = 2000

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "schema.sql"
)

# Payloads carry file contents, terminal output and env dumps. Redact the shapes
# that are cheap to recognise before anything touches disk.
REDACTIONS = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
        "[redacted-private-key]",
    ),
    (
        re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|ghr|github_pat|xox[baprs])[-_][A-Za-z0-9_\-]{12,}"),
        "[redacted-token]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted-aws-key]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|credential)s?\b\s*[:=]\s*(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1=[redacted]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [redacted]"),
)

HARNESS_ALIASES = {
    "claude-code": "claude_code",
    "claudecode": "claude_code",
    "claude": "claude_code",
    "codex-cli": "codex",
    "cursor-cli": "cursor",
    "openai-codex": "codex",
}


def normalize_harness(value: str) -> str:
    value = (value or "").strip().lower().replace(" ", "_")
    value = HARNESS_ALIASES.get(value, value)
    return value.replace("-", "_") or "unknown"


def pick(payload: dict, *names):
    """First non-empty value for any name, checked at top level then in `extra`."""
    extra = payload.get("extra")
    sources = [payload] + ([extra] if isinstance(extra, dict) else [])
    for name in names:
        for source in sources:
            value = source.get(name)
            if value not in (None, "", [], {}):
                return value
    return None


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def clean(value) -> str:
    text = as_text(value)
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:TRUNCATE]


def map_status(raw, error, event: str, has_tool: bool) -> str:
    if raw is None:
        if error or event.lower().endswith(("failure", "error")):
            return "error"
        return "success" if has_tool else "unknown"
    value = str(raw).strip().lower()
    if value in {"ok", "passed", "success", "succeeded", "completed", "complete"}:
        return "success"
    if value in {"fail", "failed", "error", "errored", "blocked", "denied"}:
        return "error"
    return "unknown"


def map_row(payload: dict, harness: str) -> dict:
    event = str(payload.get("hook_event_name") or payload.get("hook_event") or "")
    tool = pick(payload, "tool_name")
    tool_input = pick(payload, "tool_input", "tool_arguments", "args")
    tool_output = pick(payload, "tool_response", "tool_output", "result", "output")
    session_id = pick(
        payload, "session_id", "conversation_id", "thread_id", "sessionId", "task_id"
    )
    duration = pick(payload, "duration_ms", "duration")
    status_raw = pick(payload, "status")
    error = pick(payload, "error_message", "error", "error_type")

    # Cursor's post hooks are per-surface rather than per-tool: afterShellExecution
    # and afterFileEdit carry the payload directly, with no tool_name/tool_input.
    if tool is None:
        if pick(payload, "command") is not None:
            tool = "shell"
            tool_input = {"command": pick(payload, "command")}
        elif pick(payload, "file_path") is not None:
            tool = "edit"
            tool_input = {
                "file_path": pick(payload, "file_path"),
                "edits": pick(payload, "edits") or [],
            }

    try:
        duration_ms = int(float(duration)) if duration is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") 
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        "session_id": as_text(session_id)[:200],
        "harness": normalize_harness(harness),
        "tool": (as_text(tool) or "unknown")[:120],
        "tool_input": clean(tool_input),
        "tool_output": clean(tool_output),
        "status": map_status(status_raw, error, event, tool is not None),
        "duration_ms": duration_ms,
    }


def ensure_schema(con: sqlite3.Connection) -> None:
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_calls'"
    ).fetchone():
        return
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        con.executescript(fh.read())


def write(row: dict) -> None:
    os.makedirs(AOR_HOME, exist_ok=True)
    if RECORD_MODE == "jsonl":
        with open(JSONL_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return
    con = sqlite3.connect(DB_PATH, timeout=5)
    try:
        con.execute("PRAGMA busy_timeout = 5000")
        ensure_schema(con)
        con.execute(
            "INSERT INTO tool_calls "
            "(ts, session_id, harness, tool, tool_input, tool_output, status, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["ts"],
                row["session_id"],
                row["harness"],
                row["tool"],
                row["tool_input"],
                row["tool_output"],
                row["status"],
                row["duration_ms"],
            ),
        )
        con.commit()
    finally:
        con.close()


def main(argv: list) -> None:
    harness = ""
    for index, arg in enumerate(argv):
        if arg == "--harness" and index + 1 < len(argv):
            harness = argv[index + 1]
    if not harness:
        harness = os.environ.get("AOR_HARNESS") or "unknown"
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    if not isinstance(payload, dict):
        payload = {"tool_output": payload}
    write(map_row(payload, harness))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as exc:  # a broken hook must never break the agent loop
        print(f"record.py: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("{}")
