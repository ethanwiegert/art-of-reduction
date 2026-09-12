---
name: tool-tracking
description: Use when asked what an agent has been doing, or to set up tool-call logging.
---

# Instructions

The log answers one question: what work does this agent repeat? One SQLite file, one row per tool call, written by every harness that shares it.

## Setup

1. Run the installer for your harness — it prints the exact config to paste:

   ```
   bash ~/.agents/skills/tool-tracking/scripts/install.sh hermes
   bash ~/.agents/skills/tool-tracking/scripts/install.sh claude_code
   bash ~/.agents/skills/tool-tracking/scripts/install.sh codex
   bash ~/.agents/skills/tool-tracking/scripts/install.sh cursor
   ```

   It creates `~/.art-of-reduction/tool-tracking.db` and emits a snippet. Merge the snippet into the harness config yourself: the installer never overwrites an existing config file. Harness config **must** stay in the harness's own config directory — only the database is shared.
   Done when: the snippet is in the harness config and the harness has been restarted. Hermes prompts for consent on the first tool call after setup; approve it there once.

2. Prove it works — after a few tool calls, `calls` is above 0:

   ```
   python3 ~/.agents/skills/tool-tracking/scripts/report.py tools
   ```

No hook support (`install.sh none`)? Point whatever wrapper you have at `scripts/record.py`: it reads a JSON payload on stdin and takes `--harness <name>`.

## Reading it

```
python3 ~/.agents/skills/tool-tracking/scripts/report.py                 # everything
python3 ~/.agents/skills/tool-tracking/scripts/report.py repeats --min 3 # same call, 2+ sessions
python3 ~/.agents/skills/tool-tracking/scripts/report.py failures        # which tools error most
python3 ~/.agents/skills/tool-tracking/scripts/report.py sessions        # outlier session sizes
```

`repeats` is the section to act on; `lazy-automate` consumes it.

## What is stored — say this to the user

Table `tool_calls`, one row per call: `ts` (UTC), `session_id`, `harness`, `tool`, `tool_input`, `tool_output`, `status`, `duration_ms`. Full definition in `schema.sql`.

Arguments and results go to disk in plaintext, redacted for obvious secrets (private keys, provider tokens, `KEY=value` assignments) and truncated to 2000 characters each — `AOR_TRUNCATE` to change that. Redaction is a filter, not a guarantee: file contents, command output, and prompts still land in a local unencrypted database. Retention is the user's call — `DELETE FROM tool_calls WHERE ts < ...`, or delete the file.

## Pitfalls

- The hook fires synchronously on every tool call and **fails open**: a missing `python3`, a moved skill directory, or an unwritable database degrades to no logging, never to a broken agent. Silence is the failure mode — check `calls` above instead of assuming it is recording.
- If a synchronous write ever shows in your latency, set `AOR_RECORD_MODE=jsonl` to append instead of inserting, and drain it while idle: `python3 .../scripts/report.py import`.
- Harnesses disagree about payloads. Not every one reports a duration or a failing-call status: `duration_ms` is NULL and `status` is `unknown` when the payload does not say. Do not read those as measurements.
- Several harnesses write the same file. Locks and `busy_timeout` are set, but keep a shared store on a local disk, never a network mount.
