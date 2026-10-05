---
name: tool-tracking
description: Use when asked what an agent has been doing, or to set up tool-call logging.
---

# Instructions

The log answers one question: what work does this agent repeat? One SQLite file, one row per tool call, written by every harness that shares it.

## Setup

1. Run the installer for your harness from this skill's directory — it prints the exact config to paste:

   ```
   bash scripts/install.sh hermes
   bash scripts/install.sh claude_code
   bash scripts/install.sh codex
   bash scripts/install.sh cursor
   ```

   It creates `~/.art-of-reduction/tool-tracking.db` and prints the fragment; you merge it into the harness config yourself — the installer never writes there. Harness config **must** stay in the harness's own config directory — only the database is shared. The installer also prints the absolute report command; keep it.
   Done when: the fragment is in the harness config and the harness has been restarted. Hermes prompts for consent on the first tool call after setup; approve it there once.

2. Prove it works — after a few tool calls, `calls` is above 0:

   ```
   python3 scripts/report.py tools
   ```

### One log for a whole team

Run `python3 scripts/serve.py` on one host. Every harness writes to that one store, with the same mapping and redaction as `record.py`, applied server-side:

- **Any harness** (Hermes, Codex, Cursor, a custom wrapper): set `AOR_INGEST_URL` (and `AOR_INGEST_TOKEN`) in the environment the agent runs in, then set up its hook exactly as above. `record.py` forwards the payload instead of writing locally.
- **Claude Code** can skip `record.py`: paste the `type: "http"` fragment `serve.py` prints.
- **Anything that can POST JSON:** `POST /hook/<harness>` with its hook payload as the body.

Beyond localhost it refuses to start without `AOR_INGEST_TOKEN`; clients send it as `Authorization: Bearer`. The server speaks plain HTTP, so across a network put it behind a TLS reverse proxy. If the server is unreachable, `record.py` waits at most a second and then writes the row to its local store instead.

No hook support (`install.sh none`)? Point whatever wrapper you have at `scripts/record.py`: it reads a JSON payload on stdin and takes `--harness <name>`.

## Reading it

```
python3 scripts/report.py                 # everything
python3 scripts/report.py repeats --min 3 # same call, 2+ sessions
python3 scripts/report.py failures        # which tools error most
python3 scripts/report.py sessions        # outlier session sizes
```

Reports fold harness tool names into kinds (`shell`, `read`, `edit`, `search`, `web`) so repeated work counts once across harnesses; the raw name is still in the `tool` column.

`repeats` is the section to act on; `lazy-automate` consumes it. It groups calls that are identical once paths, numbers, ids, model-written `description` fields and output trimming (`2>&1`, `| tail -n 30`) are folded away, so variants of the same work (`cd x && npm test`, extra flags) count separately: check `query.py search --input "<command>"` before deciding something is rare. Its `errors` column flags a repeated call that keeps failing; script the call that works, not that one. To look up specific calls (one session, a failure, a command) use the `tool-log-search` skill.

## What is stored — say this to the user

Table `tool_calls`, one row per call: `ts` (UTC, when the hook fired - the call's end, not its start), `session_id`, `harness`, `tool`, `tool_input`, `tool_output`, `status`, `duration_ms`. Full definition in `schema.sql`.

Arguments and results go to disk in plaintext, redacted for obvious secrets (private keys, provider tokens, `key=value` and `"key": "value"` credentials, `--password`-style flags, URL passwords, Bearer/Basic auth) and truncated to 2000 characters each — `AOR_TRUNCATE` to change that. Redaction is a filter, not a guarantee: file contents, command output, and prompts still land in an unencrypted database, which the installer keeps in a `700` directory. Retention is the user's call — `DELETE FROM tool_calls WHERE ts < ...`, or delete the file.

## Pitfalls

- The hook fires synchronously on every tool call and **fails open**: a missing `python3`, a moved skill directory, or an unwritable database degrades to no logging, never to a broken agent. Silence is the failure mode — check `calls` above instead of assuming it is recording.
- Harnesses disagree about payloads. Not every one reports a duration or a failing-call status: `duration_ms` is NULL and `status` is `unknown` when the payload does not say. Do not read those as measurements. Codex is the main case: no duration, no status, and calls it counts as failed never fire the hook, so its rows are `unknown` and its failures are missing. `report.py failures` shows `unknown` per harness and leaves it out of `fail%`.
- `status` is the tool's own verdict, not the work's: `npm test | tail` exits with `tail`'s code, so a failing test run piped through it is stored as `success`. Read `tool_output` before trusting a success.
- Several harnesses write the same file. Locks and `busy_timeout` are set, but keep a shared store on a local disk, never a network mount.
