---
name: tool-log-search
description: Use to look up past tool calls - what an agent ran, what failed, what a session did - before redoing or debugging the work.
---

# Instructions

Answer questions about past agent work from the tool-call log (the `tool-tracking` skill's database), not from memory. One script, JSON Lines out, read-only:

```
python3 scripts/query.py schema                      # columns, kinds, db path
python3 scripts/query.py search [filters]            # newest first
python3 scripts/query.py trail <session_id>          # one session, in order
python3 scripts/query.py sql "SELECT ..."            # anything else
```

Needs the `tool-tracking` skill installed alongside (it shares its tool-kind folding). The database is `$AOR_HOME/tool-tracking.db` (default `~/.art-of-reduction/`). On a team store, run this on the host that runs `serve.py`, or point `AOR_HOME` at a copy.

## Pick the narrowest query

| Question | Command |
|---|---|
| Did any agent already run this? | `search --grep "gh pr checks"` |
| What failed today? | `search --status error --since 2026-10-04` |
| What did that session do? | `trail <session_id>` |
| All shell calls from Codex | `search --tool shell --harness codex` |
| What ran in one project? | `search --cwd payments-api` (substring of the working directory) |
| Which sessions touched a file? | `search --input ".env"` (inputs only; `--grep` also matches every `ls` that printed it) |
| Who changed it, and how? | `search --input core.py --tool edit`, then `--tool shell` too: agents also edit with `sed -i` and patches, which name the file, not the function |
| What repeats across sessions? | `tool-tracking`'s `report.py repeats` (it normalizes inputs first) |

Filters combine with AND: `--tool` (a kind - `shell`, `read`, `edit`, `search`, `web` - or a raw tool name), `--session`, `--harness`, `--status success|error|unknown`, `--since`/`--until` (ISO-8601 UTC prefixes), `--grep` (case-insensitive, input or output), `--input` (same, input only), `--cwd` (substring of the working directory), `--limit` (default 50, 0 = all).

## Keep output small

- `tool_input` and `tool_output` are cut to 300 characters per row, marked `...[+N]`. `--chars 0` returns them whole; ask for that only on the rows you need, by `id`: `sql "SELECT tool_output FROM tool_calls WHERE id = 42"`.
- Start with `--limit 10` and widen. Count before you list: `sql "SELECT COUNT(*) AS n FROM tool_calls WHERE status = 'error'"`.
- In SQL, `kind(tool)` folds harness names (`Bash`, `shell`, `terminal`) into one kind; use it in `GROUP BY` so the same work counts once across harnesses.

## Reading results

- Each line is one call: `id, ts, session_id, harness, cwd, tool, kind, status, duration_ms, input_chars, output_chars, tool_input, tool_output`. `output_chars` is the size before truncation, so a call whose `tool_output` stops at 2000 characters may have printed far more (null on rows from before it was recorded). No rows prints `(no rows)` on stderr and nothing on stdout.
- `status = 'unknown'` and `duration_ms = null` mean the harness did not report them, not success or zero (Codex reports neither). Compare failure rates per harness only over known statuses: `SUM(status='error') * 1.0 / SUM(status != 'unknown')`.
- `success` is the tool's exit, not the work's: a test run piped into `tail` succeeds even when tests fail. Check `tool_output`.
- Output shapes differ by harness: Claude Code stores its tool's result object (`stdout`/`stderr` for Bash), Cursor and Hermes a JSON string such as `{"output": ..., "exit_code": ...}`, Gemini CLI and Copilot CLI the text the model read. Search text, not structure.
- Inputs and outputs were redacted and truncated when recorded. A `[redacted]` marker means a secret was there; do not try to recover it.
- The connection is read-only: `sql` cannot change the log. Deleting rows is the user's call, done with `sqlite3` directly.
