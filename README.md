# art-of-reduction: find what your AI agents repeat, and turn it into scripts

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python stdlib only](https://img.shields.io/badge/python-stdlib%20only-green.svg)
![Works with Claude Code, Codex, Cursor, Hermes](https://img.shields.io/badge/agents-Claude%20Code%20%7C%20Codex%20%7C%20Cursor%20%7C%20Hermes-purple.svg)

Agent skills that **log every tool call your coding agents make, find the work they repeat across sessions, and compile it into deterministic scripts**, so the agent is needed less. Agent-agnostic: Claude Code, OpenAI Codex, Cursor and Hermes write to one shared SQLite log, and anything else can POST JSON. Pure Python standard library, no packages, no cloud.

Skills to reduce dependencies, **even the agent that runs them**.

```
npx skills add ethanwiegert/art-of-reduction
```

## Why

Agents re-derive the same work every session: the same test command, the same lookup, the same failed fix. That costs tokens and time, and it is invisible unless something records it. This repo records it, ranks it, and turns the repeats into files.

The pipeline:

1. **Record:** `tool-tracking` hooks every tool call into one local SQLite log (or one team log over HTTP).
2. **Find:** `report.py repeats` names the calls that recur across sessions and harnesses.
3. **Recall:** `tool-log-search` lets any agent check past calls before redoing or debugging work.
4. **Codify:** `lazy-automate` compiles the repeat into a script, hook, or config change.
5. **Reduce:** `art-of-reduction` keeps the resulting code, and every change set, small.

## Quickstart

```
# 1. Create the log and print the hook config for your agent
bash skills/tool-tracking/scripts/install.sh claude_code   # or: codex | cursor | hermes | none

# 2. Paste the printed fragment into that agent's config, restart it, work as usual

# 3. See what repeats
python3 skills/tool-tracking/scripts/report.py repeats
```

The installer only prints config; it never writes into your agent's settings.

## Supported agents

| Agent | Hook events | Status and duration |
|---|---|---|
| Claude Code | `PostToolUse`, `PostToolUseFailure` (command or native `http` hook) | yes |
| OpenAI Codex | `PostToolUse` | not reported; rows are `unknown`, failed calls never fire |
| Cursor | `postToolUse`, `postToolUseFailure` | yes (payload shape not yet verified live) |
| Hermes | `post_tool_call` | yes |
| Anything else | pipe JSON to `scripts/record.py --harness <name>` or `POST /hook/<name>` | if the payload has them |

Reports fold each agent's tool names into shared kinds (`shell`, `read`, `edit`, `search`, `web`), so the same work counts once no matter which agent did it.

## Does it work?

From an end-to-end sandbox round (2026-10-04): 23 real Claude Code sessions plus 12 replayed as Codex, Cursor and Hermes payloads. Every call was captured (31/31 in the final round), a scan for every planted secret found 0 leaks, and `repeats` ranked the test command (`python3 -m unittest discover tests`) as the top repeat. Six agent testers answered questions using only these skills: Opus and Sonnet scored 6/6 or 5.5/6, Haiku 5 to 5.5.

## The skills

### tool-tracking
Sets up the SQLite log and the post-tool hook, then answers what repeats across sessions, what fails, and which sessions run long. Ships the schema, an installer, a read-only report script, and `serve.py` for one shared team log.

```
python3 skills/tool-tracking/scripts/report.py            # every section
python3 skills/tool-tracking/scripts/report.py failures   # error rate per tool and harness
```

### tool-log-search
Lets an agent query the log directly: filtered search, one session's trail in order, or read-only SQL, all as JSON Lines with long fields cut so the model reads only what it asked for.

```
python3 skills/tool-log-search/scripts/query.py search --status error --limit 10
python3 skills/tool-log-search/scripts/query.py trail <session_id>
```

### lazy-automate
The rule of two: the second time the same work appears, it becomes a script, a hook, or a config change so no model is needed for it again. It picks candidates from the log, not from memory, and prefers the smallest artifact that removes the work.

### art-of-reduction
Reviews the current change set and removes concepts rather than characters: delete what is unused, merge what does two jobs, question the dependency, with guardrails so a reduction never changes behavior or strips error handling.

## The tool-call log

- **Location:** `~/.art-of-reduction/tool-tracking.db` (override with `AOR_HOME`). One file shared by every agent on the machine; each agent keeps its hook in its own config.
- **Schema:** [`skills/tool-tracking/schema.sql`](skills/tool-tracking/schema.sql). Table `tool_calls`: `ts` (UTC), `session_id`, `harness`, `tool`, `tool_input`, `tool_output`, `status`, `duration_ms`.
- **Team log:** `python3 skills/tool-tracking/scripts/serve.py` takes the same hook payloads over HTTP. Set `AOR_INGEST_URL` (and `AOR_INGEST_TOKEN`) where an agent runs and its hook forwards there; Claude Code can POST directly with a `type: "http"` hook. A token is required beyond localhost.
- **Plaintext, redacted:** obvious secrets (private keys, provider tokens, `key=value` and JSON credentials, `--password` flags, URL passwords, Bearer/Basic auth) are redacted and fields are truncated to 2000 characters (`AOR_TRUNCATE`). It is still an unencrypted local file; retention is yours.
- **Fails open:** if logging breaks, your agent never does. Check `report.py tools` shows calls above 0.

## For AI agents

Coding agents working on this repo should read [AGENTS.md](AGENTS.md). A compact map for LLMs is in [llms.txt](llms.txt).

## Requirements

`python3`, standard library only (`sqlite3` ships with it). Tests: `python3 -m unittest discover tests` from the repo root.

## License

[MIT](LICENSE)
