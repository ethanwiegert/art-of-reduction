#!/usr/bin/env python3
"""Turn the most repeated shell workflow in the tool-call log into a script.

    python3 codify.py                       # show the script for the top candidate
    python3 codify.py --write scripts/check # run it once; write it only if it works

Run from the project root: the log stores commands relative to it.

A candidate is the top `report.py workflows` row with 2+ shell steps, or else
the shell call repeated in the most sessions under 2+ spellings. Each step
becomes the full command agents ran most often for it, minus output plumbing
(`| tail`, `2>&1`). A step that failed in most of its runs is left out: that
was the wrong first try the script exists to skip. Read, edit and search steps
stay with the agent; they are judgment.

Refused, never written: a step that installs, deletes, pushes, deploys, writes
through a redirect, reaches the network, or carries a redacted value. A
script that repeats one of those unattended can do damage no rerun undoes.

--write runs the script with `sh` and keeps it only when it exits 0, as the
logged runs did. It prints the line to add to the instructions file agents
load (AGENTS.md), so every harness finds the script.

Reads the log read-only. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, os.pardir, "tool-tracking", "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS))
import report  # noqa: E402  the same folding and workflows the reports show

UNSAFE = re.compile(
    r"\b(?:rm|rmdir|mv|dd|mkfs|chmod|chown|sudo|su|kill|pkill|shutdown|reboot|ssh|scp|rsync"
    r"|curl|wget|deploy|kubectl|terraform|helm|ansible\S*)\b"
    r"|\bgit\s+(?:push|commit|reset|clean|checkout|switch|rebase|merge|tag|stash|rm|mv|restore)\b"
    r"|\b(?:pip3?|npm|pnpm|yarn|gem|cargo|go|brew|apt(?:-get)?|uv|poetry)\s+(?:install|add|publish|remove|uninstall|get)\b"
    r"|\bdocker\s+(?:push|rm|rmi|run|compose)\b"
    r"|(?<![0-9&])>(?!&|\s*/dev/null)"  # writes a file; 2>&1 and >/dev/null are fine
    r"|\[redacted"
)
HERE = re.compile(r"^cd \.\s*&&\s*")


def commands(con) -> dict:
    """signature -> (most common full command, error share), over every shell call."""
    forms, errors = {}, Counter()
    for row in con.execute("SELECT tool, cwd, tool_input, status FROM tool_calls WHERE tool_input != ''"):
        if report.kind(row["tool"]) != "shell":
            continue
        sig = report.signature("shell", row["tool_input"], row["cwd"])
        try:
            call = json.loads(report.relative(row["tool_input"], row["cwd"]))
        except ValueError:
            call = row["tool_input"]
        command = call.get("command") or call.get("cmd") if isinstance(call, dict) else call
        if isinstance(command, list):
            command = command[2] if len(command) > 2 and command[1] in ("-c", "-lc") else " ".join(map(str, command))
        if not isinstance(command, str) or not command.strip():
            continue
        command = report.WHITESPACE.sub(" ", report.OUTPUT_TRIM.sub("", command)).strip()
        command = HERE.sub("", command)  # the script runs from the project root already
        forms.setdefault(sig, Counter())[command, row["status"] == "error"] += 1
        errors[sig] += row["status"] == "error"
    picked = {}
    for sig, counter in forms.items():
        total = sum(counter.values())
        ok = Counter({cmd: n for (cmd, failed), n in counter.items() if not failed})
        best = (ok or Counter({cmd: n for (cmd, _), n in counter.items()})).most_common(1)[0][0]
        picked[sig] = (best, errors[sig] / total, len({cmd for cmd, _ in counter}))
    return picked


def candidate(con):
    """(steps as full commands, runs, sessions, turns saved per run, what it replaces) or None."""
    known = commands(con)
    for saves, _, sessions, runs, gram in report.find_workflows(con, 2):
        shell = [step.split(" ", 1)[1] for step in gram if step.startswith("shell ")]
        kept = list(dict.fromkeys(sig for sig in shell if sig in known and known[sig][1] <= 0.5))
        if len(kept) >= 2 or (kept and len(shell) > len(kept)):
            return [known[sig][0] for sig in kept], runs, sessions, len(shell) - 1, " -> ".join(gram)
    # No shell workflow: the one command re-derived under the most spellings.
    spelled = [(spellings, sig) for sig, (_, share, spellings) in known.items()
               if spellings >= 2 and share <= 0.5]
    if spelled:
        spellings, sig = max(spelled)
        return [known[sig][0]], 0, 0, 0, f"shell {sig} ({spellings} spellings)"
    return None


def main(argv: list) -> None:
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return
    target = argv[argv.index("--write") + 1] if "--write" in argv[:-1] else ""
    found = candidate(report.connect())
    if not found:
        sys.exit("no candidate yet: no shell workflow or command repeats across 2+ sessions")
    steps, runs, sessions, saves, replaces = found
    unsafe = [step for step in steps if UNSAFE.search(step)]
    print(f"replaces: {replaces}")
    if saves:
        print(f"seen {runs} times in {sessions} sessions; one call instead of {saves + 1} saves {saves} turns a run")
    if unsafe:
        sys.exit("refused: these steps change things a rerun cannot undo:\n  " + "\n  ".join(unsafe))
    script = "#!/bin/sh\n# Written by codify.py from the tool-call log.\nset -e\n" + "".join(
        f"( {step} )\n" for step in steps)
    print("\n" + script)
    if not target:
        print("dry run: add --write <path> to run it once and keep it")
        return
    run = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=600)
    if run.returncode:
        sys.exit(f"not written: it exited {run.returncode} where the logged runs succeeded\n"
                 + (run.stdout + run.stderr)[-1500:])
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w") as fh:
        fh.write(script)
    os.chmod(target, 0o755)
    print(f"wrote {target} (ran clean). Add to AGENTS.md:\n"
          f"- Run `{target}` instead of: {', '.join(steps)}.")


if __name__ == "__main__":
    main(sys.argv[1:])
