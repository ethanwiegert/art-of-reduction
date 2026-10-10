# AGENTS.md

Guide for coding agents (Claude Code, Codex, Cursor, Hermes, or any other) working on this repo. Humans: see [README.md](README.md).

## What this repo is

Four agent skills that record every tool call an agent makes, find the calls and call sequences repeated across sessions, and turn them into scripts. Each tool call is a model turn that re-reads the whole context, so calls removed are the saving the reports rank by. Each skill is a folder with a `SKILL.md` (YAML frontmatter `name` + `description`, then instructions) and optional `scripts/`. Installed with `npx skills add ethanwiegert/art-of-reduction`.

```
skills/
  tool-tracking/    record + report. schema.sql, scripts/{install.sh, record.py, serve.py, report.py}
  tool-log-search/  read-only queries over the log. scripts/query.py (imports report.py's kind folding)
  lazy-automate/    instructions only: turn repeats into scripts
  art-of-reduction/ instructions only: shrink change sets
tests/test_tool_tracking.py   all tests, stdlib unittest
```

Data flow: agent hook -> `record.py` (maps each harness's payload, measures, redacts, truncates; owns the schema and upgrades old stores via `PRAGMA user_version`) -> SQLite `~/.art-of-reduction/tool-tracking.db` -> `report.py` / `query.py`. `serve.py` runs the same mapping and redaction behind `POST /hook/<harness>` for a shared team log; `record.py` forwards there when `AOR_INGEST_URL` is set and falls back to the local store after 1s.

## Commands

```
python3 -m unittest discover tests                          # run all tests (from repo root)
bash skills/tool-tracking/scripts/install.sh <harness>      # claude_code | codex | cursor | gemini | copilot | hermes | none
python3 skills/tool-tracking/scripts/report.py [tools|repeats|workflows|failures|sessions] [--since TS]
python3 skills/tool-log-search/scripts/query.py schema|search|trail <id>|sql "<SELECT>"
python3 skills/tool-tracking/scripts/serve.py [--host H --port P]   # default 127.0.0.1:8787
```

Environment: `AOR_HOME` (store dir), `AOR_TRUNCATE` (default 2000), `AOR_INGEST_URL`, `AOR_INGEST_TOKEN`, `AOR_HARNESS`.

## Rules

- **Standard library only.** No pip packages, no build step. Every script runs with a bare `python3`.
- **Agent-agnostic.** Claude Code is one source among many. Never add a field, report column or doc that only makes sense for one harness; map harness-specific payloads to the shared schema in `record.py`, and fold tool names into kinds (`shell`, `read`, `edit`, `search`, `web`).
- **Fail open.** A hook must never block or break the agent. Errors in `record.py` degrade to no logging.
- **Redact before disk.** Redaction lives in `record.py` and runs server-side in `serve.py`; a client can never opt out. Any change to redaction needs a test with the secret shape it covers.
- **Read paths stay read-only.** `report.py` and `query.py` open the database read-only.
- **The installer never writes harness config.** It prints a fragment for the user to merge.
- **Practice the thesis.** Keep changes small: remove concepts, not characters (see `skills/art-of-reduction/SKILL.md`). Anything repeated belongs in a script, not in prose an agent re-derives.

## Known traps

- Codex reports no status or duration (`unknown` / NULL) and never fires the hook for failed calls. It has no read tool: it reads with `sed -n`/`cat`, which `report.py` groups by file.
- Gemini CLI hook timeouts are milliseconds; Claude Code and Codex use seconds, Copilot CLI `timeoutSec`.
- `cwd` is what makes paths line up across machines: `report.py` strips it from inputs. A harness that sends none (Hermes) keeps absolute paths.
- `status` is the tool's exit code: `npm test | tail` stores `success` even when tests fail.
- `ts` is when the hook fired (the call's end).
- Cursor's and Copilot CLI's payload shapes come from their docs, not a live run. Codex's come from its generated hook schema (`codex-rs/hooks/schema/generated`), Gemini CLI's from `docs/hooks/reference.md`, Claude Code's from live sessions.

## Before you open a PR

Run `python3 -m unittest discover tests` and keep it green. Update the relevant `SKILL.md` and the README when behavior or commands change.
