#!/usr/bin/env python3
"""Answer the actionable questions from the tool-call log.

    python3 report.py                    # every section
    python3 report.py tools              # calls per tool kind
    python3 report.py repeats --min 3    # the same call in 2+ sessions
    python3 report.py workflows          # the same calls in the same order, 2+ sessions
    python3 report.py failures           # failure rate per tool
    python3 report.py sessions           # session sizes and outliers

    --since TS   only calls at or after an ISO-8601 UTC prefix, e.g. 2026-10-01:
                 compare sessions before and after you automate something
    --min N      fewest calls (repeats) or runs (workflows) to show, default 3
    --limit N    rows per section, default 20

Read-only. Stdlib only; no server, no browser.

Every tool call costs a model turn, and every turn re-reads the whole context,
so calls are what automation saves: `workflows` ranks sequences by the calls
one script would replace. `~tok` is output size / 4, what calls add to the
context; it matters for noisy commands, and is an estimate, not a bill.
Tool names are folded into kinds (shell, read, edit, search, web) so the same
work counts once across harnesses; the raw name stays in the `tool` column.
"""
from __future__ import annotations

import functools
import json
import os
import re
import shlex
import sqlite3
import sys
from collections import Counter, defaultdict

AOR_HOME = os.environ.get("AOR_HOME") or os.path.join(
    os.path.expanduser("~"), ".art-of-reduction"
)
DB_PATH = os.path.join(AOR_HOME, "tool-tracking.db")
SAMPLE_CHARS = 160
CHARS_PER_TOKEN = 4
MAX_STEPS = 6  # longest workflow looked for
# Output size before truncation; rows recorded before schema v2 only have what was kept.
OUT_CHARS = "COALESCE(output_chars, length(tool_output))"

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s\"']+")
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
WHITESPACE = re.compile(r"\s+")
# How much output the agent chose to look at is not part of the work.
OUTPUT_TRIM = re.compile(r"\s*2>&1|\s*\|\s*(?:head|tail)(?:\s+-n)?(?:\s+-?\d+)?(?=\s*(?:[;&|\"]|$))")


# Model-written prose that rides along with a call (Claude Code's Bash
# `description`): it differs every time the same command runs.
PROSE_FIELDS = ("description",)

# Shell tokens that end one command and start the next.
SEPARATORS = {"&&", "||", "|", ";", "&", "(", ")"}
# Words that run another command: the command after them is the work.
WRAPPERS = {"sudo", "time", "env", "nohup", "exec", "command", "timeout"}
SUBCOMMAND = re.compile(r"[a-z][\w:-]*")  # test, run, pr, compose
# Programs whose work is the file they are given (Codex has no read tool; it runs
# `sed -n '1,200p' f`): the file is the work, not the flags before it.
READERS = {"cat", "head", "tail", "sed", "nl", "wc", "less", "more", "bat"}
PATH_KEYS = ("file_path", "absolute_path", "filePath", "path", "target_file", "notebook_path")
PATCH_FILES = re.compile(r"\*\*\* (?:Add|Update|Delete) File: (\S+)")  # Codex apply_patch


def relative(text: str, cwd: str) -> str:
    """Paths under the working directory read the same on every machine."""
    root = (cwd or "").rstrip("/")
    if root.count("/") < 2:  # '' or '/': nothing safe to strip
        return text
    return text.replace(root + "/", "").replace(root, ".")


# The log is mostly repeats, so most inputs have been seen before.
@functools.lru_cache(maxsize=1 << 16)
def normalize(text: str, cwd: str = "") -> str:
    """Collapse the parts of a call that vary run to run, so repeats line up."""
    text = relative(text, cwd)
    try:
        call = json.loads(text)
    except ValueError:
        call = None
    if isinstance(call, dict) and any(field in call for field in PROSE_FIELDS):
        text = json.dumps({k: v for k, v in call.items() if k not in PROSE_FIELDS},
                          ensure_ascii=False, sort_keys=True)
    text = OUTPUT_TRIM.sub("", text)
    text = UUID.sub("<uuid>", text)
    text = HOME_PATH.sub("/<home>", text)
    text = NUMBER.sub("<n>", text)
    return WHITESPACE.sub(" ", text).strip()[:SAMPLE_CHARS]


def command_head(command) -> str:
    """The program a shell call runs, and its subcommand.

    `cd x && python3 -m pytest -q tests/ 2>&1 | tail` -> `python -m pytest`;
    `git commit -m "..."` -> `git commit`; `npm run build -- --watch` -> `npm run build`.
    Flags, messages and output plumbing vary run to run; the work does not.
    """
    if isinstance(command, list):  # argv form: ["bash", "-lc", "npm test"]
        command = command[2] if len(command) > 2 and command[1] in ("-c", "-lc") else " ".join(map(str, command))
    # A newline ends a command too; agents send multi-line scripts.
    lexer = shlex.shlex(str(command).replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes
        tokens = str(command).split()
    words, redirect = [], False
    for token in tokens + [";"]:
        if token in SEPARATORS:
            while words and (words[0] in WRAPPERS or "=" in words[0] or words[0][:1].isdigit()):
                words.pop(0)  # sudo, FOO=1, timeout 30
            if words and words[0] != "cd":
                return head(words)
            words = []
        elif token and set(token) <= set("<>&"):  # > file, 2>&1, &>/dev/null
            if words and words[-1].isdigit():
                words.pop()
            redirect = True
        elif redirect:
            redirect = False
        else:
            words.append(token)
    return ""


def head(words: list) -> str:
    # /usr/bin/python3 is python; ./scripts/test is this project's script, so it keeps its path.
    program = words[0]
    program = os.path.basename(program) if program.startswith("/") else program.removeprefix("./")
    program = re.sub(r"^python[\d.]*$", "python", program)
    rest = words[1:]
    if program == "python" and rest[:1] == ["-m"] and len(rest) > 1:
        return f"python -m {rest[1]}"
    if program in READERS:
        files = [word for word in rest if not word.startswith("-")]
        return f"{program} {files[-1]}" if files else program
    kept = [program]
    for index, word in enumerate(rest[:2]):
        # The first argument may be a script or file; after it, only subcommand words.
        if word.startswith("-") or " " in word or (index and not SUBCOMMAND.fullmatch(word)):
            break
        kept.append(word)
    return " ".join(kept)


@functools.lru_cache(maxsize=1 << 16)
def signature(tool_kind: str, text: str, cwd: str = "") -> str:
    """What a call did, minus what varies run to run: shell calls by command,
    reads and edits by file. Repeats and workflows group on it."""
    try:
        call = json.loads(relative(text, cwd))
    except ValueError:
        call = text
    if tool_kind == "shell" and isinstance(call, str) and call.strip():
        return command_head(call)
    if isinstance(call, dict):
        command = call.get("command") or call.get("cmd")
        if tool_kind == "shell" and command:
            return command_head(command)
        if tool_kind == "edit" and isinstance(command, str) and PATCH_FILES.search(command):
            return " ".join(PATCH_FILES.findall(command))
        if tool_kind in ("read", "edit"):
            path = next((call[k] for k in PATH_KEYS if isinstance(call.get(k), str) and call[k]), "")
            if path:
                return HOME_PATH.sub("~", path)[:SAMPLE_CHARS]
    return normalize(text, cwd)


KINDS = {
    "bash": "shell",
    "shell": "shell",
    "shell_command": "shell",
    "terminal": "shell",
    "exec_command": "shell",
    "write_stdin": "shell",
    "run_shell_command": "shell",
    "read": "read",
    "read_file": "read",
    "read_many_files": "read",
    "view": "read",
    "edit": "edit",
    "multiedit": "edit",
    "write": "edit",
    "write_file": "edit",
    "create": "edit",
    "replace": "edit",
    "patch": "edit",
    "apply_patch": "edit",
    "notebookedit": "edit",
    "grep": "search",
    "glob": "search",
    "ls": "search",
    "list": "search",
    "list_directory": "search",
    "search_files": "search",
    "grep_search": "search",
    "search_file_content": "search",
    "webfetch": "web",
    "web_fetch": "web",
    "websearch": "web",
    "web_search": "web",
    "web_extract": "web",
    "google_web_search": "web",
}


def kind(tool: str) -> str:
    return KINDS.get(tool.lower(), tool.lower())


def tokens(chars) -> int:
    return round((chars or 0) / CHARS_PER_TOKEN)


def connect(since: str = "") -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        sys.exit(f"no database at {DB_PATH} - set AOR_HOME or run tool-tracking's scripts/install.sh")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.create_function("kind", 1, kind, deterministic=True)
    have = {row[1] for row in con.execute("PRAGMA table_info(tool_calls)")}
    missing = "".join(
        f", {default} AS {name}"
        for name, default in (("cwd", "''"), ("input_chars", "NULL"), ("output_chars", "NULL"))
        if name not in have
    )
    if missing or since:
        # A temp view shadows the table for this connection only: every query sees
        # the columns a not-yet-upgraded store lacks, and only calls since `since`.
        quoted = "'" + since.replace("'", "''") + "'"
        con.execute(f"CREATE TEMP VIEW tool_calls AS SELECT *{missing}"
                    f" FROM main.tool_calls WHERE ts >= {quoted}")
    return con


def table(headers, rows, empty="(nothing recorded yet)") -> str:
    if not rows:
        return empty
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
    return "\n".join(line.rstrip() for line in lines)


def section_tools(con, limit: int) -> None:
    print("\n== calls per tool kind ==")
    rows = con.execute(
        "SELECT kind(tool) AS tool, COUNT(*) AS calls, SUM(status='error') AS errors,"
        f"       ROUND(AVG(duration_ms)) AS avg_ms, SUM({OUT_CHARS}) AS chars"
        " FROM tool_calls GROUP BY kind(tool) ORDER BY calls DESC LIMIT ?",
        (limit,),
    ).fetchall()
    print(
        table(
            ("tool", "calls", "errors", "avg_ms", "~tok"),
            [(r["tool"], r["calls"], r["errors"], r["avg_ms"] or "-", tokens(r["chars"]))
             for r in rows],
        )
    )


def section_failures(con, limit: int) -> None:
    print("\n== failure rate per tool and harness ==")
    # fail% is over calls whose status is known: a harness that never reports
    # failures (Codex) shows as unknown, not as 0% failing.
    rows = con.execute(
        "SELECT kind(tool) AS tool, harness, COUNT(*) AS calls,"
        "       SUM(status='error') AS errors, SUM(status='unknown') AS unknown,"
        "       ROUND(100.0 * SUM(status='error') / NULLIF(SUM(status!='unknown'), 0), 1) AS pct"
        " FROM tool_calls GROUP BY kind(tool), harness"
        " ORDER BY pct DESC, errors DESC, calls DESC LIMIT ?",
        (limit,),
    ).fetchall()
    print(
        table(
            ("tool", "harness", "calls", "errors", "unknown", "fail%"),
            [(r["tool"], r["harness"], r["calls"], r["errors"], r["unknown"],
              "-" if r["pct"] is None else r["pct"]) for r in rows],
            empty="(no failures recorded)",
        )
    )


def section_repeats(con, minimum: int, limit: int) -> None:
    print(f"\n== calls repeated across sessions (>= {minimum} calls, 2+ sessions) ==")
    groups = defaultdict(lambda: {"calls": 0, "errors": 0, "chars": 0, "sessions": set(),
                                  "harnesses": set(), "forms": Counter()})
    for row in con.execute(
        f"SELECT tool, harness, cwd, tool_input, session_id, status, {OUT_CHARS} AS chars"
        " FROM tool_calls WHERE tool_input != ''"
    ):
        tool_kind = kind(row["tool"])
        group = groups[(tool_kind, signature(tool_kind, row["tool_input"], row["cwd"]))]
        group["calls"] += 1
        group["errors"] += row["status"] == "error"
        group["chars"] += row["chars"] or 0
        group["sessions"].add(row["session_id"])
        group["harnesses"].add(row["harness"])
        group["forms"][normalize(row["tool_input"], row["cwd"])] += 1
    repeats = [
        (tool, data["calls"], len(data["sessions"]), data["errors"], tokens(data["chars"]),
         len(data["forms"]), ",".join(sorted(data["harnesses"])), call[:60],
         data["forms"].most_common(1)[0][0][:100])
        for (tool, call), data in groups.items()
        if data["calls"] >= minimum and len(data["sessions"]) >= 2
    ]
    # Each call is a model turn: the most calls is the most to save.
    repeats.sort(key=lambda item: (-item[1], -item[2], -item[4], item[0], item[7]))
    print(
        table(
            ("tool", "calls", "sessions", "errors", "~tok", "forms", "harnesses", "call",
             "most common form"),
            repeats[:limit],
            empty="(no cross-session repeats yet)",
        )
    )


def section_workflows(con, minimum: int, limit: int) -> None:
    print(f"\n== workflows: the same calls in the same order (>= {minimum} runs, 2+ sessions) ==")
    trails = defaultdict(list)
    for row in con.execute(
        "SELECT session_id, tool, cwd, tool_input FROM tool_calls"
        " WHERE session_id != '' ORDER BY ts, id"
    ):
        tool_kind = kind(row["tool"])
        step = f"{tool_kind} {signature(tool_kind, row['tool_input'], row['cwd'])}"
        trail = trails[row["session_id"]]
        if not trail or trail[-1] != step:  # a retry is one step
            trail.append(step)
    # A step seen in one session cannot be part of a cross-session workflow, so it
    # splits the trail; that keeps the search small on a large log.
    step_sessions = Counter(step for trail in trails.values() for step in set(trail))
    sessions, runs = Counter(), Counter()
    for trail in trails.values():
        seen = set()
        segment = []
        for step in trail + [None]:
            if step is not None and step_sessions[step] >= 2:
                segment.append(step)
                continue
            for size in range(2, min(MAX_STEPS, len(segment)) + 1):
                for start in range(len(segment) - size + 1):
                    gram = tuple(segment[start:start + size])
                    runs[gram] += 1
                    seen.add(gram)
            segment = []
        sessions.update(seen)
    found = {gram: count for gram, count in sessions.items()
             if count >= 2 and runs[gram] >= minimum}
    # A sequence only ever seen inside a longer one, in as many sessions, is that one.
    covered = Counter()
    for gram, count in found.items():
        for part in (gram[1:], gram[:-1]):
            covered[part] = max(covered[part], count)
    workflows = [
        ((len(gram) - 1) * runs[gram], len(gram), count, runs[gram],
         " -> ".join(step[:48] for step in gram))
        for gram, count in found.items() if covered[gram] < count
    ]
    # One script call instead of N steps saves N-1 turns every run.
    workflows.sort(key=lambda item: (-item[0], -item[2], item[4]))
    print(
        table(
            ("saves", "steps", "sessions", "runs", "sequence"),
            workflows[:limit],
            empty="(no cross-session workflows yet)",
        )
    )


def section_sessions(con, limit: int) -> None:
    print("\n== session sizes ==")
    rows = con.execute(
        "SELECT session_id, GROUP_CONCAT(DISTINCT harness) AS harnesses,"
        "       COUNT(*) AS calls, MIN(ts) AS started, SUM(status='error') AS errors,"
        f"      SUM({OUT_CHARS}) AS chars"
        " FROM tool_calls WHERE session_id != ''"
        " GROUP BY session_id ORDER BY calls DESC LIMIT ?",
        (limit,),
    ).fetchall()
    counts = sorted(
        (
            r[0]
            for r in con.execute(
                "SELECT COUNT(*) FROM tool_calls WHERE session_id != ''"
                " GROUP BY session_id"
            )
        ),
        reverse=True,
    )
    median = counts[len(counts) // 2] if counts else 0
    print(
        table(
            ("calls", "errors", "~tok", "harness", "started", "session"),
            [
                (
                    r["calls"],
                    r["errors"],
                    tokens(r["chars"]),
                    r["harnesses"],
                    (r["started"] or "")[:19],
                    r["session_id"],
                )
                for r in rows
            ],
        )
    )
    if counts:
        print(f"\nmean {sum(counts) / len(counts):.1f} calls per session, median {median}")
    if counts and median and counts[0] >= 3 * median:
        print(
            f"outlier: the largest session used {counts[0]} calls, "
            f"{counts[0] / median:.1f}x the median ({median}). "
            "Long sessions are where an agent loops - read its tool trail before "
            "adding more instructions."
        )


def main(argv: list) -> None:
    flags = {"--min": 3, "--limit": 20, "--since": ""}
    rest = []
    queue = list(argv)
    while queue:
        arg = queue.pop(0)
        if arg in flags:
            if not queue:
                sys.exit(f"{arg} needs a value")
            value = queue.pop(0)
            if arg == "--since":
                flags[arg] = value
                continue
            try:
                flags[arg] = int(value)
            except ValueError:
                sys.exit(f"{arg} needs an integer value")
        else:
            rest.append(arg)
    command = rest[0] if rest else "all"
    if command in {"--help", "-h"}:
        print(__doc__.strip())
        return
    minimum, limit = flags["--min"], flags["--limit"]

    con = connect(flags["--since"])
    calls, sessions = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT NULLIF(session_id, '')) FROM tool_calls").fetchone()
    since = f" since {flags['--since']}" if flags["--since"] else ""
    print(f"{DB_PATH}: {calls} calls in {sessions} sessions{since}")
    sections = {
        "tools": lambda: section_tools(con, limit),
        "failures": lambda: section_failures(con, limit),
        "sessions": lambda: section_sessions(con, limit),
        "repeats": lambda: section_repeats(con, minimum, limit),
        "workflows": lambda: section_workflows(con, minimum, limit),
    }
    if command == "all":
        for name in ("tools", "failures", "sessions", "repeats", "workflows"):
            sections[name]()
    elif command in sections:
        sections[command]()
    else:
        sys.exit(f"unknown section: {command}")
    con.close()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except sqlite3.Error as exc:
        sys.exit(f"sqlite error: {exc}")
