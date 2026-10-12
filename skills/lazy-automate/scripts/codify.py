#!/usr/bin/env python3
"""Turn the most repeated shell workflow in the tool-call log into a script.

    python3 codify.py                       # show the script for the top candidate
    python3 codify.py --write scripts/check # run it once; write it only if it works

Run from the project root. Only calls logged in a directory with the same
name count (paths differ across machines; names do not), and the log stores
commands relative to that directory. A harness that sends no directory
(Hermes) is left out.

A candidate is the top `report.py workflows` row with 2+ shell steps, or else
the shell call repeated in the most sessions under 2+ spellings. Each step
becomes the full command agents ran most often for it, minus output plumbing
(`| tail`, `2>&1`). A step that failed in most of its runs is left out: that
was the wrong first try the script exists to skip. Read, edit and search steps
stay with the agent; they are judgment.

Only read and check commands are scripted: tests, linters without --fix,
type checks, builds, and read-only git and file commands (SAFE below). Any
other program, a redirect into a file, command substitution or a redacted
value is refused, never run: a script that repeats an install, delete, push
or network call unattended can do damage no rerun undoes. Write those by hand.

--write runs the script with `sh` and keeps it only when it exits 0, as the
logged runs did. It prints the line to add to the instructions file agents
load (AGENTS.md), so every harness finds the script.

Reads the log read-only. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections import Counter

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, os.pardir, "tool-tracking", "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS))
import report  # noqa: E402  the same folding and workflows the reports show

# program -> the subcommands that only read or check (None: any arguments).
SAFE = {
    **dict.fromkeys(("pytest", "mypy", "tsc", "flake8", "pylint", "eslint", "jest", "vitest",
                     "cat", "head", "tail", "wc", "ls", "grep", "rg", "echo", "test", "true",
                     "pwd", "diff", "cd"), None),
    "python": {"-m pytest", "-m unittest", "-m mypy", "-m flake8", "-m pylint"},
    "ruff": {"check"},
    **dict.fromkeys(("npm", "yarn", "pnpm"),
                    {"test", "run test", "run lint", "run build", "run check", "run typecheck"}),
    "cargo": {"test", "check", "clippy", "build"},
    "go": {"test", "vet", "build"},
    "make": {"test", "check", "lint"},
    "git": {"status", "diff", "log", "show"},
}
# Flags that write, execute or load code, matched as `flag` or `flag=value`.
WRITES = {"--fix", "--fix-only", "--write", "--in-place", "--delete", "--update-snapshots",
          "--output", "--ext-diff", "--textconv", "--pre", "--add-noqa"}
PROGRAM_WRITES = {"jest": {"-u"}, "vitest": {"-u"}, "go": {"-o"}, "pytest": {"-p"},
                  "python": {"-p"}, "tail": {"-f", "-F", "--follow"}}
# Runners whose extra arguments are more targets or scripts to run.
ONE_TARGET = {"make", "npm", "yarn", "pnpm"}


def step_unsafe(words: list) -> str:
    while words and "=" in words[0]:
        words = words[1:]  # FOO=1 pytest
    if not words:
        return ""
    program = re.sub(r"^python[\d.]*$", "python", os.path.basename(words[0]))
    allowed = SAFE.get(program, ())
    if allowed is not None:
        sub = next((sub.split() for sub in allowed if words[1:1 + len(sub.split())] == sub.split()), None)
        if sub is None:
            return f"`{program}` is not on the read/check list"
        extra = words[1 + len(sub):]
        if program in ONE_TARGET and any(not w.startswith("-") and "=" not in w for w in extra):
            return f"`{program}` with more targets"
    flags = WRITES | PROGRAM_WRITES.get(program, set())
    if any(w.split("=", 1)[0] in flags for w in words):
        return f"`{program}` with a flag that writes or runs code"
    if program == "tsc" and "--noEmit" not in words:
        return "`tsc` without --noEmit writes files"
    return ""


def unsafe(command: str) -> str:
    """Why a command is not safe to rerun unattended, or '' when it only reads or checks."""
    if "[redacted" in command or "$(" in command or "`" in command or "\n" in command:
        return "substitution, line break or redacted value"
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return "unbalanced quotes"
    words = []
    for index, token in enumerate(tokens + [";"]):
        if token in {"&", "|&", ">|"} or "(" in token or ")" in token:
            return "background job, subshell or forced redirect"
        if token in report.SEPARATORS or token in {"&&", "||", ";;"}:
            reason = step_unsafe(words)
            if reason:
                return reason
            words = []
        elif ">" in token and set(token) <= set("<>&"):
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
            if not (target == "/dev/null" or (token.endswith("&") and target.isdigit())):
                return "redirect into a file"
            words = words[:-1] if words and words[-1].isdigit() else words
        elif not set(token) <= set("<>&"):
            words.append(token)
    return ""


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
        command = re.sub(r"[ \t]+", " ", report.OUTPUT_TRIM.sub("", command)).strip()  # a line break stays: it is a second command
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
    target = ""
    if "--write" in argv:
        if argv[-1] == "--write":
            sys.exit("--write needs a path, e.g. --write scripts/check")
        target = argv[argv.index("--write") + 1]
    project = os.path.basename(os.getcwd())
    print(f"project: {project} (calls logged in a directory of that name)")
    found = candidate(report.connect(project=project))
    if not found:
        sys.exit("no candidate yet: no shell workflow or command repeats across 2+ sessions")
    steps, runs, sessions, saves, replaces = found
    refused = [f"{step}  ({unsafe(step)})" for step in steps if unsafe(step)]
    print(f"replaces: {replaces}")
    if saves:
        print(f"seen {runs} times in {sessions} sessions; one call instead of {saves + 1} saves {saves} turns a run")
    if refused:
        sys.exit("refused: only read and check commands are scripted; write these by hand:\n  "
                 + "\n  ".join(refused))
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
