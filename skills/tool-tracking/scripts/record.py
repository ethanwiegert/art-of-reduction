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
    AOR_INGEST_URL   send the payload to a shared serve.py instead of the local
                     store; it maps and redacts on arrival
    AOR_INGEST_TOKEN bearer token for AOR_INGEST_URL
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
try:
    TRUNCATE = max(0, int(os.environ.get("AOR_TRUNCATE") or 2000))
except ValueError:
    TRUNCATE = 2000
# Redaction runs on this much more than is kept, so a secret that straddles the
# cut still matches whole, and a megabyte of output costs no more than a page.
REDACT_MARGIN = 8192

INGEST_URL = os.environ.get("AOR_INGEST_URL", "").rstrip("/")

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "schema.sql"
)
SCHEMA_VERSION = 2
# Columns added after the first schema, for stores created before them.
ADDED_COLUMNS = (
    ("cwd", "TEXT NOT NULL DEFAULT ''"),
    ("input_chars", "INTEGER"),
    ("output_chars", "INTEGER"),
)
COLUMNS = ("ts", "session_id", "harness", "cwd", "tool", "tool_input", "tool_output",
           "status", "duration_ms", "input_chars", "output_chars")

# Where a harness says which part of a result the model read (Gemini CLI,
# Copilot CLI), that part is the output; the rest is display metadata.
MODEL_FACING = ("llmContent", "textResultForLlm", "text_result_for_llm")
# Result fields no model reads: Claude Code's Edit returns the whole file as it
# was before the edit.
NOT_MODEL_FACING = ("originalFile",)

# Payloads carry file contents, terminal output and env dumps. Redact the shapes
# that are cheap to recognise before anything touches disk.
REDACTIONS = (
    # A key cut short (`head id_rsa`, truncated output) has no END line: redact
    # the key body that is there.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r"(?:.*?-----END [A-Z ]*PRIVATE KEY-----|[\w+/=\s\\:,.-]*)",
            re.S,
        ),
        "[redacted-private-key]",
    ),
    (
        re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|ghr|github_pat|xox[baprs])[-_][A-Za-z0-9_\-]{12,}"),
        "[redacted-token]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted-aws-key]"),
    # KEY=value, "key": "value" (raw or JSON-escaped), OPENAI_API_KEY=..., X-Api-Key: ...
    # A quoted value is redacted up to its closing quote, spaces and all. Token
    # counts (max_tokens, token_count) are settings, not secrets.
    (
        re.compile(
            r"(?i)((?:api[_-]?key|secret|token(?!s\b|s?_?count)|passw(?:or)?d|credential)[\w-]*\\?[\"']?"
            r"\s*[:=]\s*)(\\?[\"'])(?:(?!\2).)+\2"
        ),
        r"\1\2[redacted]\2",
    ),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|secret|token(?!s\b|s?_?count)|passw(?:or)?d|credential)[\w-]*\\?[\"']?"
            r"\s*[:=]\s*\\?[\"']?)(?:[^\s\"'\\,}&]|&(?!\w+=))+"
        ),
        r"\1[redacted]",
    ),
    (re.compile(r"(?i)(--(?:api-key|password|passwd|secret|token)[= ])\S+"), r"\1[redacted]"),
    (re.compile(r"(://[^/\s:@]+:)[^/\s@]+@"), r"\1[redacted]@"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 [redacted]"),
)


def normalize_harness(value: str) -> str:
    return (value or "").strip().lower().replace("-", "_")[:40] or "unknown"


def pick(payload: dict, *names):
    """First non-empty value for any name at the top level."""
    for name in names:
        value = payload.get(name)
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


def clean(value) -> tuple:
    """(redacted, truncated text; length before truncation)."""
    text = as_text(value)
    kept = text[: TRUNCATE + REDACT_MARGIN]
    for pattern, replacement in REDACTIONS:
        kept = pattern.sub(replacement, kept)
    return kept[:TRUNCATE], len(text)


def map_status(raw, error, event: str, harness: str) -> str:
    if error or event.lower().endswith("failure"):
        return "error"
    if raw is not None:
        value = str(raw).strip().lower()
        if value in {"ok", "passed", "success", "succeeded", "completed", "complete"}:
            return "success"
        if value in {"fail", "failed", "failure", "error", "errored", "blocked", "denied",
                     "rejected"}:
            return "error"
        return "unknown"
    # Codex skips PostToolUse when its handler reports failure, but a shell call
    # that exits non-zero can still count as handled (codex-rs/core/src/tools/
    # registry.rs), and the payload has no exit code: neither proves success.
    # Gemini CLI fires AfterTool for failures too, with `error` in the result.
    return "success" if harness in {"claude_code", "cursor", "gemini"} else "unknown"


def map_row(payload: dict, harness: str) -> dict:
    harness = normalize_harness(harness)
    # Hermes nests result, status and duration_ms under `extra`; top level wins.
    if isinstance(payload.get("extra"), dict):
        payload = {**payload["extra"], **payload}
    event = str(payload.get("hook_event_name") or payload.get("hook_event") or "")
    # Copilot CLI's own payload is camelCase; the rest use snake_case.
    tool = pick(payload, "tool_name", "toolName")
    tool_input = pick(payload, "tool_input", "tool_arguments", "args", "toolArgs")
    tool_output = pick(payload, "tool_response", "tool_output", "tool_result", "toolResult",
                       "result", "output")
    session_id = pick(
        payload, "session_id", "conversation_id", "thread_id", "sessionId", "task_id"
    )
    roots = payload.get("workspace_roots")  # Cursor
    cwd = pick(payload, "cwd", "workingDirectory") or (
        roots[0] if isinstance(roots, list) and roots else ""
    )
    duration = pick(payload, "duration_ms", "duration")
    status_raw = pick(payload, "status")
    error = pick(payload, "error_message", "error", "error_type")
    if isinstance(tool_output, dict):
        status_raw = status_raw or pick(tool_output, "resultType", "result_type")
        error = error or pick(tool_output, "error")
        facing = pick(tool_output, *MODEL_FACING)
        tool_output = facing if facing is not None else {
            k: v for k, v in tool_output.items() if k not in NOT_MODEL_FACING
        }

    try:
        duration_ms = int(float(duration)) if duration is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    tool_input, input_chars = clean(tool_input)
    tool_output, output_chars = clean(tool_output if tool_output is not None else error)
    now = datetime.now(timezone.utc)
    return {
        "ts": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "session_id": as_text(session_id)[:200],
        "harness": harness,
        "cwd": as_text(cwd)[:500],
        "tool": (as_text(tool) or "unknown")[:120],
        "tool_input": tool_input,
        "tool_output": tool_output,
        "status": map_status(status_raw, error, event, harness),
        "duration_ms": duration_ms,
        "input_chars": input_chars,
        "output_chars": output_chars,
    }


def ensure_schema(con: sqlite3.Connection) -> None:
    if con.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        con.executescript(fh.read())  # IF NOT EXISTS: a new store gets every column
    have = {row[1] for row in con.execute("PRAGMA table_info(tool_calls)")}
    for name, declaration in ADDED_COLUMNS:
        if name not in have:
            try:
                con.execute(f"ALTER TABLE tool_calls ADD COLUMN {name} {declaration}")
            except sqlite3.OperationalError as exc:  # a concurrent hook added it first
                if "duplicate column" not in str(exc):
                    raise
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()


def connect() -> sqlite3.Connection:
    """Open the store for writing, creating or upgrading it first."""
    os.makedirs(AOR_HOME, mode=0o700, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5)
    try:
        con.execute("PRAGMA busy_timeout = 5000")
        ensure_schema(con)
    except BaseException:
        con.close()
        raise
    return con


def write(row: dict) -> None:
    con = connect()
    try:
        con.execute(
            f"INSERT INTO tool_calls ({', '.join(COLUMNS)})"
            f" VALUES ({', '.join('?' * len(COLUMNS))})",
            [row[column] for column in COLUMNS],
        )
        con.commit()
    finally:
        con.close()


def forward(payload: dict, harness: str) -> None:
    import urllib.request  # half of this hook's start-up time; only forwarding needs it

    request = urllib.request.Request(
        f"{INGEST_URL}/hook/{normalize_harness(harness)}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = os.environ.get("AOR_INGEST_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    urllib.request.urlopen(request, timeout=1).close()


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
    if INGEST_URL:
        try:
            forward(payload, harness)
        except OSError as exc:  # host down: keep the row locally, never lose it
            print(f"record.py: forward failed, wrote locally: {exc}", file=sys.stderr)
            write(map_row(payload, harness))
    else:
        write(map_row(payload, harness))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as exc:  # a broken hook must never break the agent loop
        print(f"record.py: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("{}")
