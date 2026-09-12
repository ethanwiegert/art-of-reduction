#!/usr/bin/env bash
# Hermes post_tool_call hook: pipe the payload to record.py, stay quiet.
#
# Register in ~/.hermes/config.yaml (paths must be absolute; run install.sh for
# the resolved block):
#
#   hooks:
#     post_tool_call:
#       - matcher: ".*"
#         command: "python3 /abs/path/hooks/hermes.sh"
#         timeout: 10
#
# Hermes prompts for consent on first use of an (event, command) pair — the
# first tool call after setup raises that prompt once.
root="$(cd "$(dirname "$0")/.." && pwd)"
record="$root/scripts/record.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$record" ]; then
  payload="$(cat -)" || payload=""
  printf '%s' "${payload:-{\}}" | python3 "$record" --harness hermes >/dev/null 2>&1
fi
printf '{}\n'
exit 0
