#!/usr/bin/env python3
"""Field test: real agent sessions through the real hooks, scored on the moat.

    python3 evals/run.py                  # sonnet, every task twice
    python3 evals/run.py --model opus --runs 1 --keep

Needs Claude Code (`claude`) on PATH and signed in; it runs about 20 headless
sessions on a throwaway fixture project, so it costs real tokens. Other
harnesses are not run live: every captured call is replayed as Codex, Cursor,
Gemini CLI, Copilot CLI and Hermes payloads through record.py.

1. before   each task x runs on a fresh fixture; hook -> record.py -> serve.py
2. automate one lazy-automate session reads the log and builds scripts (not logged)
3. after    the same tasks on the fixture it automated
4. replay   every call from 1 re-sent as each other harness, into the same store

The scorecard covers the three things the project claims (ROADMAP.md):
turns saved, every harness folding into one log, and nothing leaking. It is
printed as markdown and saved to evals/results/, next to the previous run.
"""
from __future__ import annotations

import glob
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "skills", "tool-tracking", "scripts")
RECORD = os.path.join(SCRIPTS, "record.py")
RESULTS = os.path.join(REPO, "evals", "results")
sys.path.insert(0, SCRIPTS)
import report  # noqa: E402  kind() and signature(): how the reports fold calls

UNITTEST = "python3 -m unittest discover tests"
TASKS = {  # name: (prompt, command that must pass afterwards, or None)
    "tests": ("Run this project's tests and tell me which ones fail.", None),
    "fix": ("Fix the bug in apply_discount and make sure the tests pass.", UNITTEST),
    "add": ("Add a function line_count(lines) to invoicer/core.py that returns the number"
            " of invoice lines, with a unit test.", UNITTEST),
    "explain": ("Explain what total() in invoicer/core.py does, in two sentences.", None),
    "config": ("Which outside services does this project talk to? Check .env and config.yaml.", None),
}
TOOLS = "Bash Read Edit Write Glob Grep"
WINDOW = 5  # a stored run of this many characters of a planted secret is a leak


def fake(n: int) -> str:
    """Consonants only: no run of them occurs in real output by chance."""
    return "".join(secrets.choice("BCDFGHJKLMNPQRSTVWXZ") for _ in range(n))


def fixture(path: str) -> dict:
    """A small Python project with a planted bug and fresh fake secrets."""
    planted = {"stripe": fake(24), "openai": fake(24), "aws": fake(16), "db": fake(10),
               "smtp": fake(6) + "&" + fake(6), "webhook": fake(20)}
    files = {
        "README.md": f"# invoicer\nRun tests: `{UNITTEST}`\nSecrets live in .env (never commit it).\n",
        ".env": (f"STRIPE_SECRET_KEY=sk_live_{planted['stripe']}\n"
                 f"DATABASE_URL=postgres://billing:{planted['db']}@db.internal:5432/invoices\n"
                 f"OPENAI_API_KEY=sk-proj-{planted['openai']}\n"
                 f"AWS_ACCESS_KEY_ID=AKIA{planted['aws']}\n"),
        "config.yaml": (f"smtp:\n  host: mail.internal\n  user: invoices\n"
                        f"  password: {planted['smtp']}\nwebhook_token: whk_{planted['webhook']}\n"),
        "invoicer/__init__.py": "",
        "invoicer/core.py": '''"""Tiny invoicing helpers."""


def subtotal(lines):
    """Sum of qty * unit_price over invoice lines."""
    return sum(line["qty"] * line["unit_price"] for line in lines)


def apply_discount(amount, pct):
    """Return amount after a percentage discount (pct in 0..100)."""
    return amount - amount * pct


def total(lines, pct=0, tax_rate=0.08):
    discounted = apply_discount(subtotal(lines), pct)
    return round(discounted * (1 + tax_rate), 2)
''',
        "tests/__init__.py": "",
        "tests/test_core.py": '''import unittest
from invoicer.core import subtotal, apply_discount, total

LINES = [{"qty": 2, "unit_price": 10.0}, {"qty": 1, "unit_price": 5.0}]


class CoreTest(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(subtotal(LINES), 25.0)

    def test_discount(self):
        self.assertEqual(apply_discount(100.0, 10), 90.0)

    def test_total(self):
        self.assertEqual(total(LINES, pct=20), 21.6)
''',
    }
    for name, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(path, name)), exist_ok=True)
        with open(os.path.join(path, name), "w") as fh:
            fh.write(body)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return planted


def agent_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in {"CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
                        "AOR_INGEST_URL", "AOR_INGEST_TOKEN", "AOR_HOME"}}
    return {**env, **extra}


def claude(cwd: str, prompt: str, model: str, env: dict) -> dict:
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "json",
         "--allowedTools", TOOLS],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900,
    )
    try:
        return json.loads(out.stdout)
    except ValueError:
        sys.exit(f"claude failed in {cwd}:\n{out.stderr[-2000:]}")


def hook(work: str, raw: str) -> dict:
    """Claude Code settings: keep the raw payload for replay, then record it."""
    script = os.path.join(work, "hook.sh")
    with open(script, "w") as fh:
        fh.write(f"#!/bin/sh\np=$(cat)\nprintf '%s\\n' \"$p\" >> '{raw}'\n"
                 f"printf '%s' \"$p\" | exec python3 '{RECORD}' --harness claude_code\n")
    os.chmod(script, 0o755)
    entry = [{"matcher": "", "hooks": [{"type": "command", "command": script, "timeout": 10}]}]
    return {"hooks": {"PostToolUse": entry, "PostToolUseFailure": entry}}


def session(src: str, dest: str, task: str, model: str, settings: dict, env: dict) -> dict:
    shutil.copytree(src, dest)
    os.makedirs(os.path.join(dest, ".claude"), exist_ok=True)
    with open(os.path.join(dest, ".claude", "settings.json"), "w") as fh:
        json.dump(settings, fh)
    prompt, check = TASKS[task]
    result = claude(dest, prompt, model, env)
    usage = result.get("usage") or {}
    passed = None
    if check:
        passed = subprocess.run(check, shell=True, cwd=dest, capture_output=True).returncode == 0
    return {
        "task": task, "session_id": result.get("session_id", ""),
        "turns": result.get("num_turns") or 0,
        "cost": result.get("total_cost_usd") or 0.0,
        "context": sum(usage.get(k) or 0 for k in
                       ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
        "passed": passed,
    }


def phase(name, src, work, model, runs, raw, env) -> list:
    settings = hook(work, raw)
    return [session(src, os.path.join(work, f"{name}-{task}-{run}"), task, model, settings, env)
            for run in range(runs) for task in TASKS]


# Each harness's own payload for one Claude Code call (shapes: record.py, AGENTS.md).
def replay_as(harness: str, payload: dict, sid: str, cwd: str):
    name, inp = payload.get("tool_name", ""), payload.get("tool_input") or {}
    error = payload.get("error")
    out = payload.get("tool_response")
    out = error if error else (out if isinstance(out, str) else json.dumps(out))
    path = inp.get("file_path") or inp.get("path") or ""
    command = inp.get("command") or (f"cat {path}" if name == "Read" else
                                     f"rg {inp.get('pattern', '')}" if name in {"Grep", "Glob"} else "")
    if harness == "codex":
        if error:
            return None  # Codex never fires the hook for a failed call
        tool_input = {"patch": f"*** Update File: {path}\n"} if name in {"Edit", "Write"} else {"command": command}
        return {"session_id": sid, "turn_id": "t1", "hook_event_name": "PostToolUse", "cwd": cwd,
                "tool_name": "apply_patch" if "patch" in tool_input else "Bash",
                "tool_input": tool_input, "tool_response": out}
    if harness == "cursor":
        tool = {"Bash": "Shell", "Read": "Read", "Edit": "Edit", "Write": "Write"}.get(name, "Grep")
        base = {"conversation_id": sid, "tool_name": tool, "tool_input": inp, "cwd": cwd, "duration": 100}
        if error:
            return {**base, "hook_event_name": "postToolUseFailure", "error_message": out}
        return {**base, "hook_event_name": "postToolUse", "tool_output": json.dumps({"output": out})}
    if harness == "gemini":
        tool, args = {"Bash": ("run_shell_command", {"command": command}),
                      "Read": ("read_file", {"absolute_path": path}),
                      "Edit": ("replace", {"file_path": path}),
                      "Write": ("write_file", {"file_path": path})}.get(name, ("search_file_content", inp))
        response = {"error": {"message": out}} if error else {"llmContent": out}
        return {"session_id": sid, "hook_event_name": "AfterTool", "cwd": cwd,
                "tool_name": tool, "tool_input": args, "tool_response": response}
    if harness == "copilot":
        tool, args = {"Bash": ("bash", {"command": command}), "Read": ("view", {"path": path}),
                      "Edit": ("edit", {"path": path}), "Write": ("create", {"path": path})}.get(name, ("grep", inp))
        return {"sessionId": sid, "cwd": cwd, "toolName": tool, "toolArgs": args,
                "toolResult": {"resultType": "failure" if error else "success", "textResultForLlm": out}}
    tool = {"Bash": "terminal", "Read": "read_file", "Edit": "patch", "Write": "write_file"}.get(name, "search_files")
    return {"hook_event_name": "post_tool_call", "session_id": sid, "cwd": cwd, "tool_name": tool,
            "tool_input": inp, "extra": {"result": json.dumps({"output": out}), "duration_ms": 100,
                                         "status": "error" if error else "ok"}}


def replay(raw: str, env: dict) -> int:
    sent = 0
    payloads = [json.loads(line) for line in open(raw)] if os.path.exists(raw) else []
    for harness in ("codex", "cursor", "gemini", "copilot", "hermes"):
        for payload in payloads:
            sid, old = f"{harness}-{payload.get('session_id', '')}", payload.get("cwd") or ""
            new = f"/home/dev-{harness}/invoicer"
            moved = json.loads(json.dumps(payload).replace(old, new)) if old else payload
            body = replay_as(harness, moved, sid, new)
            if body:
                subprocess.run([sys.executable, RECORD, "--harness", harness], input=json.dumps(body),
                               text=True, env=env, capture_output=True, check=True)
                sent += 1
    return sent


def rows(work: str) -> list:
    """Every row in every store under work: the shared one and any local fallback."""
    found = []
    for db in glob.glob(os.path.join(work, "**", "tool-tracking.db"), recursive=True):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        found += [dict(r, store=db) for r in con.execute("SELECT * FROM tool_calls")]
        con.close()
    return found


def leaks(found: list, planted: dict) -> list:
    hits = []
    for name, value in planted.items():
        windows = {value[i:i + WINDOW] for i in range(len(value) - WINDOW + 1)} - {""}
        for row in found:
            text = f"{row['tool_input']}\n{row['tool_output']}"
            if any(w in text for w in windows if "&" not in w):
                hits.append(f"{name} in {row['harness']} {row['tool']} row {row['id']}")
    return hits


def folded(found: list) -> tuple:
    """The call the most harnesses share once folded, and how many share it."""
    groups = {}
    for row in found:
        if row["tool_input"]:
            k = report.kind(row["tool"])
            key = (k, report.signature(k, row["tool_input"], row["cwd"]))
            groups.setdefault(key, []).append(row["harness"])
    if not groups:
        return 0, ""
    key, harnesses = max(groups.items(), key=lambda item: (len(set(item[1])), len(item[1])))
    return len(set(harnesses)), f"{key[0]} {key[1][:60]}"


def summary(sessions: list, found: list) -> dict:
    ids = {s["session_id"] for s in sessions}
    calls = [sum(1 for r in found if r["session_id"] == sid) for sid in ids]
    checked = [s["passed"] for s in sessions if s["passed"] is not None]
    return {"turns": sum(s["turns"] for s in sessions), "context": sum(s["context"] for s in sessions),
            "cost": round(sum(s["cost"] for s in sessions), 4),
            "calls_per_session": round(sum(calls) / len(calls), 1) if calls else 0,
            "checks_passed": f"{sum(checked)}/{len(checked)}"}


def scorecard(result: dict, last: dict | None) -> str:
    b, a = result["before"], result["after"]
    pct = lambda x, y: f"{(y - x) / x:+.0%}" if x else "n/a"
    prev = lambda key: (last or {}).get("headline", {}).get(key, "-")
    head = result["headline"]
    lines = [f"## Field test {result['date']} ({result['model']}, {result['runs']} runs per task)", "",
             "| | this run | last run |", "|---|---|---|"]
    for label, key in (("Turns saved by automation", "turns_saved"), ("Context tokens saved", "context_saved"),
                       ("Cost saved", "cost_saved"), ("Harnesses folded onto one call", "harnesses_folded"),
                       ("Planted-secret leaks", "leaks"), ("Calls captured / sent", "captured"),
                       ("Task checks passed (before, after)", "checks")):
        lines.append(f"| {label} | {head[key]} | {prev(key)} |")
    lines += ["", f"Turns {b['turns']} -> {a['turns']} ({pct(b['turns'], a['turns'])}), "
              f"context {b['context']:,} -> {a['context']:,}, cost ${b['cost']} -> ${a['cost']}, "
              f"calls per session {b['calls_per_session']} -> {a['calls_per_session']}.",
              f"Most-folded call: {result['folded_call']}"]
    if result["leaks"]:
        lines += ["", "Leaks:"] + [f"- {hit}" for hit in result["leaks"]]
    return "\n".join(lines)


def main(argv: list) -> None:
    opts = {"--model": "sonnet", "--runs": "2"}
    for index, arg in enumerate(argv[:-1]):
        if arg in opts:
            opts[arg] = argv[index + 1]
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return
    if not shutil.which("claude"):
        sys.exit("needs Claude Code: `claude` is not on PATH")
    model, runs = opts["--model"], int(opts["--runs"])
    work = tempfile.mkdtemp(prefix="aor-eval-")
    shared, token = os.path.join(work, "shared"), secrets.token_hex(16)
    server = subprocess.Popen([sys.executable, os.path.join(SCRIPTS, "serve.py"), "--port", "0"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                              env=agent_env(AOR_HOME=shared, AOR_INGEST_TOKEN=token))
    try:
        url = next(line.split()[1].rsplit("/hook", 1)[0] for line in server.stdout
                   if line.startswith("listening:"))
        logged = agent_env(AOR_HOME=os.path.join(work, "local"), AOR_INGEST_URL=url, AOR_INGEST_TOKEN=token)
        base, raw = os.path.join(work, "fixture"), os.path.join(work, "raw-before.jsonl")
        planted = fixture(base)

        print(f"before: {len(TASKS) * runs} sessions", file=sys.stderr)
        before = phase("before", base, work, model, runs, raw, logged)

        print("automate: one lazy-automate session", file=sys.stderr)
        auto = os.path.join(work, "automated")
        shutil.copytree(base, auto)
        claude(auto, f"Read {REPO}/skills/lazy-automate/SKILL.md and follow it for this project. Its "
               f"tool-call log is in the store AOR_HOME points at: read it with python3 "
               f"{SCRIPTS}/report.py and {REPO}/skills/tool-log-search/scripts/query.py. Build the "
               "artifacts in this directory. Do not change invoicer/ or tests/.",
               model, agent_env(AOR_HOME=shared))
        for keep in ("invoicer", "tests"):  # the bug stays planted for the after run
            shutil.rmtree(os.path.join(auto, keep))
            shutil.copytree(os.path.join(base, keep), os.path.join(auto, keep))
        built = sorted(os.path.relpath(p, auto) for p in glob.glob(os.path.join(auto, "**"), recursive=True)
                       if os.path.isfile(p) and ".git" not in p.split(os.sep)
                       and not os.path.exists(os.path.join(base, os.path.relpath(p, auto))))

        print(f"after: {len(TASKS) * runs} sessions", file=sys.stderr)
        after = phase("after", auto, work, model, runs, os.path.join(work, "raw-after.jsonl"), logged)

        print("replay: as codex, cursor, gemini, copilot, hermes", file=sys.stderr)
        replayed = replay(raw, logged)
        found = rows(work)
        sent = sum(1 for path in glob.glob(os.path.join(work, "raw-*.jsonl")) for _ in open(path)) + replayed
    finally:
        server.kill()
        server.wait()

    b, a = summary(before, found), summary(after, found)
    width, call = folded(found)
    hits = leaks(found, planted)
    saved = lambda key: f"{(b[key] - a[key]) / b[key]:.0%}" if b[key] else "n/a"
    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "model": model, "runs": runs,
        "headline": {"turns_saved": saved("turns"), "context_saved": saved("context"),
                     "cost_saved": saved("cost"), "harnesses_folded": f"{width}/6",
                     "leaks": len(hits), "captured": f"{len(found)}/{sent}",
                     "checks": f"{b['checks_passed']}, {a['checks_passed']}"},
        "before": b, "after": a, "built": built, "folded_call": call, "leaks": hits,
        "sessions": {"before": before, "after": after},
    }
    os.makedirs(RESULTS, exist_ok=True)
    previous = sorted(glob.glob(os.path.join(RESULTS, "*.json")))
    last = json.load(open(previous[-1])) if previous else None
    out = os.path.join(RESULTS, f"{result['date']}-{model}.json")
    with open(out, "w") as fh:
        json.dump(result, fh, indent=1)
    print(scorecard(result, last))
    print(f"\nlazy-automate built: {', '.join(built) or 'nothing'}\nsaved: {os.path.relpath(out, REPO)}")
    if "--keep" in argv:
        print(f"work dir (holds the planted fake secrets): {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
