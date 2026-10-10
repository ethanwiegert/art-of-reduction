# art-of-reduction: find what your AI agents repeat, and turn it into scripts

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python stdlib only](https://img.shields.io/badge/python-stdlib%20only-green.svg)
![Works with Claude Code, Codex, Cursor, Gemini CLI, Copilot CLI, Hermes](https://img.shields.io/badge/agents-Claude%20Code%20%7C%20Codex%20%7C%20Cursor%20%7C%20Gemini%20CLI%20%7C%20Copilot%20CLI%20%7C%20Hermes-purple.svg)

Agent skills that **log every tool call your coding agents make, find the work they repeat across sessions, and compile it into deterministic scripts**, so the agent is needed less. Agent-agnostic: Claude Code, OpenAI Codex, Cursor, Gemini CLI, GitHub Copilot CLI and Hermes write to one shared SQLite log, and anything else can POST JSON. Pure Python standard library, no packages, no cloud.

Skills to reduce dependencies, **even the agent that runs them**.

```
npx skills add ethanwiegert/art-of-reduction
```

## Why

Agents re-derive the same work every session: the same test command, the same lookup, the same failed fix. That costs tokens and time, and it is invisible unless something records it. This repo records it, ranks it, and turns the repeats into files.

What it costs is calls, not characters. Every tool call is a model turn, and every turn re-reads the whole context: in measured Claude Code sessions that was about 30,000 tokens per turn, against a few hundred for a typical tool output. So the reports rank by the calls a script would remove.

The pipeline:

1. **Record:** `tool-tracking` hooks every tool call into one local SQLite log (or one team log over HTTP).
2. **Find:** `report.py workflows` and `repeats` name the call sequences and calls that recur across sessions and harnesses, ranked by the turns a script would save.
3. **Recall:** `tool-log-search` lets any agent check past calls before redoing or debugging work.
4. **Codify:** `lazy-automate` compiles the repeat into a script, hook, or config change.
5. **Reduce:** `art-of-reduction` keeps the resulting code, and every change set, small.

## Quickstart

```
# 1. Create the log and print the hook config for your agent
bash skills/tool-tracking/scripts/install.sh claude_code   # or: codex | cursor | hermes | none

# 2. Paste the printed fragment into that agent's config, restart it, work as usual

# 3. See what repeats
python3 skills/tool-tracking/scripts/report.py workflows
python3 skills/tool-tracking/scripts/report.py repeats
```

The installer only prints config; it never writes into your agent's settings.

## Supported agents

| Agent | Hook events | Status and duration |
|---|---|---|
| Claude Code | `PostToolUse`, `PostToolUseFailure` (command or native `http` hook) | yes |
| OpenAI Codex | `PostToolUse` | not reported; rows are `unknown`, failed calls never fire |
| Cursor | `postToolUse`, `postToolUseFailure` | yes (payload shape from docs, not yet verified live) |
| Gemini CLI | `AfterTool` | status yes, duration no |
| GitHub Copilot CLI | `postToolUse`, `postToolUseFailure` | status yes, duration no (payload shape from docs, not yet verified live) |
| Hermes | `post_tool_call` | yes |
| Anything else | pipe JSON to `scripts/record.py --harness <name>` or `POST /hook/<name>` | if the payload has them |

Reports fold each agent's tool names into shared kinds (`shell`, `read`, `edit`, `search`, `web`) and paths relative to the agent's working directory, so the same work counts once no matter which agent, or whose machine, did it.

## Does it work?

Measured end to end on 2026-10-05, with live headless Claude Code sessions on a small Python repo with a planted bug. Eight sessions ran four everyday tasks twice: run the tests, fix the bug, add a function with a test, and explain a function. Then one `lazy-automate` session read the log (`report.py workflows`, `repeats`, then `query.py` for real examples) and built three files: a `scripts/test` that prints only failures, an `AGENTS.md` naming it with a one-line project map, and a `CLAUDE.md` importing it. The same eight sessions then ran again:

| Same 8 tasks | Before | After |
|---|---|---|
| Model turns | 68 | 41 (−40%) |
| Context tokens | 2.10M | 1.12M (−46%) |
| Cost | $0.389 | $0.258 (−34%) |
| Mean tool calls per session (`report.py sessions`) | 7.5 | 4.1 |

What the log showed before: `python -m pytest` failed in 5 of 5 sessions (pytest was not installed), and the working test command appeared in six different spellings. After: no pytest, no `ls`/`find` orientation, one form of the test command. "Add a function with a test" did not get cheaper; reading and editing is judgment, not a script.

The same real sessions, replayed as Codex, Gemini CLI, Copilot CLI, Cursor and Hermes payloads into one `serve.py` store, folded together: the test command counted once across five harnesses, and one file read through `file_path`, `path` and `absolute_path` counted as one. An earlier round (2026-10-04, 23 sessions) captured every call (31/31) and found 0 leaks of planted secrets.

Rerun all of it with `python3 evals/run.py` (needs Claude Code; it runs about 20 live sessions). Each run adds a scorecard to `evals/results/`, and `ROADMAP.md` tracks the history.

## The skills

### tool-tracking
Sets up the SQLite log and the post-tool hook, then answers which call sequences and calls repeat across sessions, what fails, and which sessions run long. Ships the schema, an installer, a read-only report script, and `serve.py` for one shared team log.

```
python3 skills/tool-tracking/scripts/report.py                     # every section
python3 skills/tool-tracking/scripts/report.py workflows           # repeated sequences, by turns a script saves
python3 skills/tool-tracking/scripts/report.py sessions --since 2026-10-05   # did automating it pay off?
```

### tool-log-search
Lets an agent query the log directly: filtered search, one session's trail in order, or read-only SQL, all as JSON Lines with long fields cut so the model reads only what it asked for.

```
python3 skills/tool-log-search/scripts/query.py search --status error --limit 10
python3 skills/tool-log-search/scripts/query.py trail <session_id>
```

### lazy-automate
The rule of two: the second time the same work appears, it becomes a script, a hook, or a config change so no model is needed for it again. It picks candidates from the log, not from memory, matches each pattern to an artifact (a workflow becomes one script, a command agents get wrong becomes one line in `AGENTS.md`), and checks afterwards that calls per session went down.

### art-of-reduction
Reviews the current change set and removes concepts rather than characters: delete what is unused, merge what does two jobs, question the dependency, with guardrails so a reduction never changes behavior or strips error handling.

## The tool-call log

- **Location:** `~/.art-of-reduction/tool-tracking.db` (override with `AOR_HOME`). One file shared by every agent on the machine; each agent keeps its hook in its own config.
- **Schema:** [`skills/tool-tracking/schema.sql`](skills/tool-tracking/schema.sql). Table `tool_calls`: `ts` (UTC), `session_id`, `harness`, `cwd`, `tool`, `tool_input`, `tool_output`, `status`, `duration_ms`, `input_chars`, `output_chars` (sizes before truncation). Older stores upgrade in place on the next call.
- **Team log:** `python3 skills/tool-tracking/scripts/serve.py` takes the same hook payloads over HTTP. Set `AOR_INGEST_URL` (and `AOR_INGEST_TOKEN`) where an agent runs and its hook forwards there; Claude Code can POST directly with a `type: "http"` hook. A token is required beyond localhost.
- **Plaintext, redacted:** obvious secrets (private keys, including ones cut short, provider tokens, `key=value` and JSON credentials, `--password` flags, URL passwords, Bearer/Basic auth) are redacted and fields are truncated to 2000 characters (`AOR_TRUNCATE`). It is still an unencrypted local file; retention is yours.
- **Fails open:** if logging breaks, your agent never does. Check `report.py tools` shows calls above 0. The hook adds about 40 ms per call (69 ms for a 2 MB output).

## For AI agents

Coding agents working on this repo should read [AGENTS.md](AGENTS.md). A compact map for LLMs is in [llms.txt](llms.txt).

## Requirements

`python3`, standard library only (`sqlite3` ships with it). Tests: `python3 -m unittest discover tests` from the repo root.

## License

[MIT](LICENSE)
