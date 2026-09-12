# art-of-reduction skills repo

Skills to reduce dependencies, **even the agent that runs them**.

## Install

One command to access the skills in your favorite agent/harness:

```
npx skills add ethanwiegert/art-of-reduction
```

## Goal

Reduce dependencies, and dependency on AI for your workflows.

Every skill here pushes the same direction: fewer concepts in the code, fewer steps in the workflow, and fewer turns of an agent spent on work that should be a script. The repo is three skills and a set of runnable scripts, and it tries to hold to its own thesis — anything repeated is a file, not a paragraph of instructions the agent re-derives each time.

### art-of-reduction
The core skill: review the current change set and remove concepts rather than characters. Delete what is unused, merge what is doing two jobs, question the dependency, drop comments that only restate the code — with guardrails, because a reduction that changes behavior or strips error handling is not a reduction. Includes the dependency triage and the list of things you never hand-roll.

### lazy-automate
The rule of two: the second time the same work appears, it becomes a script, a hook, or a config change so no model is needed for it again. It finds its candidates in the tool-call log — the same call repeated across sessions — rather than guessing from memory, and it prefers the smallest artifact that removes the work.

### tool-tracking
Sets up a local SQLite database and a post-tool hook that records every tool call, then answers the questions worth asking: what repeats across sessions, what fails, and which sessions run long. Ships the schema, per-harness hook configs, an installer, and a read-only report script, so setup is "run the installer and paste the snippet" rather than a description the agent re-implements.

```
python3 ~/.agents/skills/tool-tracking/scripts/report.py
```

## The tool-call log

- **Location:** `~/.art-of-reduction/tool-tracking.db` (one shared database; each harness sets up its own hook in its own config).
- **Schema:** `skills/tool-tracking/schema.sql` — `tool_calls` with `ts` (UTC), `session_id`, `harness`, `tool`, `tool_input`, `tool_output`, `status`, `duration_ms`, indexed by tool, session, time, and status.
- **Supported harnesses:** Hermes (`post_tool_call` shell hook), Claude Code (`PostToolUse`), Codex (`PostToolUse`), Cursor (`postToolUse` / `afterShellExecution` / `afterFileEdit`). Anything else: point a wrapper at `scripts/record.py`, which maps payloads field-by-field.
- **Stored in plaintext.** Arguments and results are redacted for obvious secrets and truncated to 2000 characters each, but they are still written to a local unencrypted database. Retention is yours: delete rows or the file.
- **It fails open.** Logging breaks; your agent never does.

## Requirements

`python3` (standard library only — no packages) and `sqlite3`, which ships with Python. The hooks are POSIX shell scripts.
