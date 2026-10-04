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
| Which sessions touched a file? | `sql "SELECT DISTINCT session_id FROM tool_calls WHERE instr(tool_input, 'serve.py')"` |
| What repeats across sessions? | `tool-tracking`'s `report.py repeats` (it normalizes inputs first) |

Filters combine with AND: `--tool` (a kind - `shell`, `read`, `edit`, `search`, `web` - or a raw tool name), `--session`, `--harness`, `--status success|error|unknown`, `--since`/`--until` (ISO-8601 UTC prefixes), `--grep` (case-insensitive, input or output), `--limit` (default 50, 0 = all).

## Keep output small

- `tool_input` and `tool_output` are cut to 300 characters per row, marked `...[+N]`. `--chars 0` returns them whole; ask for that only on the rows you need, by `id`: `sql "SELECT tool_output FROM tool_calls WHERE id = 42"`.
- Start with `--limit 10` and widen. Count before you list: `sql "SELECT COUNT(*) AS n FROM tool_calls WHERE status = 'error'"`.
- In SQL, `kind(tool)` folds harness names (`Bash`, `shell`, `terminal`) into one kind; use it in `GROUP BY` so the same work counts once across harnesses.

## Reading results

- Each line is one call: `id, ts, session_id, harness, tool, kind, status, duration_ms, tool_input, tool_output`. No rows prints `(no rows)` on stderr and nothing on stdout.
- `status = 'unknown'` and `duration_ms = null` mean the harness did not report them, not success or zero.
- Inputs and outputs were redacted and truncated when recorded. A `[redacted]` marker means a secret was there; do not try to recover it.
- The connection is read-only: `sql` cannot change the log. Deleting rows is the user's call, done with `sqlite3` directly.
