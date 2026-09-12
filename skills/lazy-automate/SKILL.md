---
name: lazy-automate
description: Use when the same work comes up twice. Compile it into something deterministic.
---

# Instructions

The second time you do something, stop doing it. Turn it into a script, a hook, or a config change so it happens with no model in the loop. The goal is not a smarter agent; it is an agent that is needed less.

## Rule of two

First time: do the work. Second time, or a clear repeat: build the artifact. Name the repetition you acted on.

## Find candidates in data, not memory

If `~/.art-of-reduction/tool-tracking.db` exists (the `tool-tracking` skill), read it:

```
python3 ~/.agents/skills/tool-tracking/scripts/report.py repeats
python3 ~/.agents/skills/tool-tracking/scripts/report.py failures
python3 ~/.agents/skills/tool-tracking/scripts/report.py sessions
```

`repeats` is the list to work from: the same tool called with the same normalized input across two or more sessions. Tool count is not a signal — read/grep/shell always dominate any count. Cross-session repetition is the signal.

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

## Pitfalls

- An automation the user has to remember to run is not automation. Put it where the work already happens — a hook, a make target, a project script — instead of documenting it in a README.
- Twice with *different* inputs is not a repetition; the rule of two is a floor, not a trigger on its own.
- Prefer extending an existing script or skill over adding a new one. Artifact sprawl is the same problem one level up.
