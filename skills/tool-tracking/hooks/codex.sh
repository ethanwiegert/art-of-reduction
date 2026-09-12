#!/usr/bin/env bash
# Codex PostToolUse hook. Merge hooks/codex.json into ~/.codex/hooks.json.
# Codex requires a one-time trust review of new hooks (`/hooks` in the CLI)
# before it will run them.
root="$(cd "$(dirname "$0")/.." && pwd)"
record="$root/scripts/record.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$record" ]; then
  payload="$(cat -)" || payload=""
  printf '%s' "${payload:-{\}}" | python3 "$record" --harness codex >/dev/null 2>&1
fi
printf '{}\n'
exit 0
