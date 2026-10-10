# Roadmap

## The moat

Everything here serves one of three claims. If an item serves none of them, it goes under **Not now**.

1. **One platform for every harness.** Calls from Claude Code, Codex, Cursor, Gemini CLI, Copilot CLI and Hermes land in one log and fold into the same calls.
2. **Reviewing sessions and tools.** The log shows what agents repeat, where they fail, and which sessions run long.
3. **Automating agent tasks to save tokens.** Repeats become scripts, and the turns they save are measured.

`evals/run.py` measures all three in one scorecard: turns saved by automation, harnesses folded onto one call, and planted-secret leaks.

## The loop

The loop runs once a week and covers one item.

1. **Pick.** Take the top item from **Next**. Name the claim it serves and the scorecard number it should move.
2. **Build.** Do the smallest change that moves that number (`skills/art-of-reduction/SKILL.md`), on a branch, keeping `python3 -m unittest discover tests` green.
3. **Field test.** Run `python3 evals/run.py`. Commit the result under `evals/results/`.
4. **Guided review.** A fresh reviewer that did not write the change works through `REVIEW.md`. Use Sonnet or better, because Haiku has missed real leaks.
5. **Ship or kill.** Open a draft PR with the scorecard delta and the review verdict. Ethan merges. If the number did not move, say so and close it.

Guardrails:
- A change that adds a leak, drops a harness from the fold, or lowers turns saved does not ship.
- If turns saved stalls for two weeks, the next pick is the reason it stalled, not a new feature.
- Move each finished item to **Done** with its PR and scorecard line.

## Next

Items are ranked. Each one names the claim it serves.

1. **Codify as a script** (3). `lazy-automate` is prose today. Build a stdlib script that takes the top `workflows` row, drafts the script, runs it, and keeps it only if it reproduces the calls' result. It refuses calls with irreversible side effects, such as push, deploy, rm or network writes (the TraceCompiler guardrail).
2. **Payoff as a command** (2, 3). Turn the "check it paid off" step into `report.py payoff --since TS`: calls per session and the targeted workflow, before and after.
3. **Fold command variants** (1, 2). `cd x && npm test` and `npm test` count as separate repeats today. Fold them so repeats are not under-counted.
4. **Portable output** (1, 3). Emit what Codify builds as an `AGENTS.md` line plus a script, so every harness picks it up, not only Claude Code.
5. **Fallback rows reach the shared store** (1). Rows written locally when `serve.py` was down never get forwarded. Send them on the next successful forward.
6. **Verify Cursor live** (1). Cursor's payload shape comes from its docs and has never been checked against a live run.

## Not now

Dashboards and a docs site, a Share layer or MCP server, SSO and access control, billing, an OTel collector, and a CI pipeline. Paperclip integration waits on Ethan's call.

## Done

- Record layer for six harnesses, shared ingest, redaction (PRs #1 to #5).
- Repeats and workflows ranked by turns saved; measured −40% turns (PR #6).

## Scorecard history

| Date | Item | Turns saved | Harnesses folded | Leaks |
|---|---|---|---|---|
| 2026-10-05 | baseline (manual run, README) | 40% | 5 replayed + Claude Code | 0 |
