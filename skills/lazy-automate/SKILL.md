---
name: lazy-automate
description: Use when the same work comes up twice. Compile it into something deterministic.
---

# Instructions

The second time you do something, stop doing it. Turn it into a script, a hook, or a config change so it happens with no model in the loop. The goal is not a smarter agent; it is an agent that is needed less.

## Rule of two

First time: do the work. Second time, or a clear repeat: build the artifact. Name the repetition you acted on.

## Find candidates in data, not memory

If `~/.art-of-reduction/tool-tracking.db` exists (the `tool-tracking` skill creates it), read it with that skill's `scripts/report.py`:

```
python3 <tool-tracking>/scripts/report.py workflows   # the same calls in the same order, 2+ sessions
python3 <tool-tracking>/scripts/report.py repeats     # the same call, 2+ sessions
python3 <tool-tracking>/scripts/report.py sessions    # calls per session: the number to bring down
```

What you are saving is calls. Every tool call is a model turn, and every turn re-reads the whole context (about 30k tokens per turn in a measured Claude Code session, against a few hundred for a typical tool output). One call that replaces four saves three turns every time the work comes up. `workflows` ranks sequences by exactly that (`saves` = (steps − 1) × runs); `repeats` groups one call by what it does (`python -m pytest`, `src/core.py`) however it was spelled. Raw tool counts are not a signal: read, grep and shell dominate every count. Cross-session repetition is.

Match what the log shows to the artifact:

| In the log | Build |
|---|---|
| A workflow: the same steps in order | One script that runs them, called in one step |
| A repeat with `errors`: the agent tries the wrong command first | One line naming the right command in the instructions file agents load (`AGENTS.md`; `CLAUDE.md` and `GEMINI.md` can import it) |
| A repeat with many `forms`: one command, re-derived each session | The canonical command as a script or make target, named in that file |
| The same files read at the start of most sessions | A short project map in that file, so the agent reads less to orient |
| High `~tok` per call: a noisy command | A wrapper that prints only what the agent acts on (failures, a summary) |

Before building, pull a few real examples of the candidate with the `tool-log-search` skill (`query.py search --input "<command>" --limit 5`) so the script handles the inputs that actually occur.

Without the database, look for: the same sequence of steps run for a new input; the same file edited the same way; the same manual check after every change.

Do not automate parsing JSON, calling an API, or looping logic. Those are code-level concerns; they are not workflow automation, and deduplicating them is `art-of-reduction`'s job.

## The artifact

In order of preference:

1. A shell command or one-line script the user runs (default).
2. A small script committed into the project, with a test.
3. A skill — only when the trigger is a judgment call, the input genuinely varies, and the workflow is worth the context it costs in every session.

## What "deterministic" means here

A runnable artifact that produces the same output for the same input, with no model in the loop and no user decision except its arguments. If a step still needs the agent to look at something and decide, it is not finished — reduce the step, or reduce the decision.

## Confirm once

Show the artifact and one worked example (input → output) before wiring it in. One confirmation, not a plan review. After that it runs unattended.

## Check it paid off

Note the date you wired it in. Once a few sessions have run, compare `report.py sessions --since <that date>` (mean calls per session) with the sessions before it, and check the workflow you targeted has dropped out of `report.py workflows --since <that date>`. If neither moved, the agent is not finding the artifact: put it where the agent already looks, or remove it.

## Pitfalls

- An automation the user has to remember to run is not automation. Put it where the work already happens — a hook, a make target, a project script — instead of documenting it in a README.
- Twice with *different* inputs is not a repetition; the rule of two is a floor, not a trigger on its own.
- Prefer extending an existing script or skill over adding a new one. Artifact sprawl is the same problem one level up.
- The log remembers the code as it was. Check every file, function and command an artifact names against the current tree, not against past calls.
