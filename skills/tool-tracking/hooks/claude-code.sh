#!/usr/bin/env bash
# Claude Code PostToolUse hook. Merge hooks/claude-code.json into
# ~/.claude/settings.json (global) or .claude/settings.json (project).
root="$(cd "$(dirname "$0")/.." && pwd)"
record="$root/scripts/record.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$record" ]; then
  payload="$(cat -)" || payload=""
  printf '%s' "${payload:-{\}}" | python3 "$record" --harness claude_code >/dev/null 2>&1
fi
# Claude Code appends stdout to the tool result Claude sees; keep it empty.
exit 0
