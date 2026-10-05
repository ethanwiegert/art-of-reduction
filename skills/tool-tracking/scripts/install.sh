#!/usr/bin/env bash
# One-shot setup for the tool-call log.
#
#   ./install.sh                 # create the store + list harnesses
#   ./install.sh hermes          # print the YAML block to merge
#   ./install.sh claude_code     # print the JSON fragment to merge
#   ./install.sh codex
#   ./install.sh cursor
#   ./install.sh gemini
#   ./install.sh copilot
#   ./install.sh none            # no native hook: env vars for a custom wrapper
#
# Idempotent: re-running never drops data and never writes into a harness config;
# it prints the fragment for you to merge. Only the database is created.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"      # .../tool-tracking/scripts
AOR_HOME="${AOR_HOME:-$HOME/.art-of-reduction}"
HARNESS="${1:-print}"
RECORD="$SKILL_DIR/record.py"
PY=python3
command -v "$PY" >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

mkdir -p "$AOR_HOME" && chmod 700 "$AOR_HOME"   # the log holds command output
# record.py owns the schema: it creates the store or upgrades an older one.
AOR_HOME="$AOR_HOME" "$PY" - "$SKILL_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import record
record.connect().close()
print(f"store ready: {record.DB_PATH}")
PY

hook_block() {
  cat <<EOF
hooks:
  post_tool_call:
    - matcher: ".*"
      command: "$PY '$RECORD' --harness hermes"
      timeout: 10
EOF
}

# Claude Code, Codex and Gemini CLI share this JSON shape: a "hooks" object
# mapping event names to matcher blocks. Print the fragment and where it goes;
# never write the harness config ourselves.
emit_hooks() { # $1 = harness, $2 = target, $3 = timeout in the harness's unit, rest = events
  "$PY" - "$RECORD" "$@" <<'PY'
import json, shlex, sys
record, harness, target, timeout, events = shlex.quote(sys.argv[1]), *sys.argv[2:5], sys.argv[5:]
entry = {"matcher": "", "hooks": [
    {"type": "command", "command": f"python3 {record} --harness {harness}", "timeout": int(timeout)}]}
print(f'Merge this fragment under the top-level "hooks" key of {target}:\n')
print(json.dumps({event: [entry] for event in events}, indent=2))
PY
}

case "$HARNESS" in
  hermes)
    cat <<'EOF'
Merge this block under the existing `hooks:` key in ~/.hermes/config.yaml,
restart Hermes, then approve the one-time consent prompt on the first tool call:

EOF
    hook_block
    ;;
  claude_code)
    emit_hooks claude_code "~/.claude/settings.json (or .claude/settings.json for this repo only)" 10 PostToolUse PostToolUseFailure
    ;;
  codex)
    emit_hooks codex "~/.codex/hooks.json" 10 PostToolUse
    cat <<'EOF'

Run `/hooks` in Codex to review and trust the new hook (Codex skips untrusted
hooks) before restarting it.
EOF
    ;;
  cursor)
    "$PY" - "$RECORD" <<'PY'
import json, shlex, sys
command = f"python3 {shlex.quote(sys.argv[1])} --harness cursor"
print("Merge this into .cursor/hooks.json (or ~/.cursor/hooks.json for all projects):\n")
print(json.dumps({"version": 1, "hooks": {
    "postToolUse": [{"command": command}],
    "postToolUseFailure": [{"command": command}],
}}, indent=2))
PY
    cat <<'EOF'

Cursor resolves relative command paths against the hooks.json file, so the
absolute path above is what you want.
EOF
    ;;
  gemini)
    # Gemini CLI fires AfterTool for failed calls too, and counts its timeout in ms.
    emit_hooks gemini "~/.gemini/settings.json (or .gemini/settings.json for one project)" 10000 AfterTool
    ;;
  copilot)
    "$PY" - "$RECORD" <<'PY'
import json, shlex, sys
hook = {"type": "command", "bash": f"python3 {shlex.quote(sys.argv[1])} --harness copilot",
        "timeoutSec": 10}
print("Save this as .github/hooks/art-of-reduction.json in the repository"
      " (Copilot CLI loads every .github/hooks/*.json):\n")
print(json.dumps({"version": 1, "hooks": {
    "postToolUse": [hook],
    "postToolUseFailure": [hook],
}}, indent=2))
print("\nThe path is this machine's: list the file in .git/info/exclude unless every"
      " teammate has the skill at the same path.")
PY
    ;;
  none)
    cat <<EOF
No native hook needed. Point your wrapper at record.py and it will map the
payload automatically:

    export AOR_HARNESS=your_harness      # or: record.py --harness your_harness
    export AOR_HOME="$AOR_HOME"
    # every tool call:  printf '%s' "\$PAYLOAD" | $PY $RECORD
EOF
    ;;
  *)
    cat <<EOF
Pass a harness name to print the config for it:
    $0 claude_code | codex | cursor | gemini | copilot | hermes | none
EOF
    ;;
esac

cat <<EOF

Nothing here is readable until calls accumulate. Check with:
    $PY $SKILL_DIR/report.py
EOF
