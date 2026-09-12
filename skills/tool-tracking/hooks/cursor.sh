#!/usr/bin/env bash
# Cursor hook. Copy hooks/cursor.json to .cursor/hooks.json in the project (or
# ~/.cursor/hooks.json for every project) and fix the command path inside it.
#
# Cursor post hooks are per-surface (postToolUse, afterShellExecution,
# afterFileEdit) and carry surface payloads rather than a tool_name/tool_input
# pair; record.py maps them onto the shared schema.
root="$(cd "$(dirname "$0")/.." && pwd)"
record="$root/scripts/record.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$record" ]; then
  payload="$(cat -)" || payload=""
  printf '%s' "${payload:-{\}}" | python3 "$record" --harness cursor >/dev/null 2>&1
fi
exit 0
