#!/usr/bin/env bash
# One-shot setup for the tool-call log.
#
#   ./install.sh                 # create the store + list harnesses
#   ./install.sh hermes          # print the YAML block to merge
#   ./install.sh claude_code     # print the JSON fragment to merge
#   ./install.sh codex
#   ./install.sh cursor
#   ./install.sh none            # no native hook: env vars for a custom wrapper
#
# Idempotent: re-running never drops data and never writes into a harness config;
# it prints the fragment for you to merge. Only the database is created.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"      # .../tool-tracking/scripts
ROOT="$(cd "$SKILL_DIR/.." && pwd)"             # .../tool-tracking
AOR_HOME="${AOR_HOME:-$HOME/.art-of-reduction}"
HARNESS="${1:-print}"
DB="$AOR_HOME/tool-tracking.db"
RECORD="$SKILL_DIR/record.py"
PY=python3
command -v "$PY" >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

mkdir -p "$AOR_HOME"
"$PY" - "$DB" "$ROOT/schema.sql" <<'PY'
import sqlite3, sys
db, schema = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
con.executescript(open(schema, encoding="utf-8").read())
con.commit()
print(f"store ready: {db}")
PY

hook_block() {
  cat <<EOF
hooks:
  post_tool_call:
    - matcher: ".*"
      command: "$PY $RECORD --harness hermes"
      timeout: 10
EOF
}

# Claude Code and Codex share this JSON shape: a "hooks" object mapping event
# names to matcher blocks. Print the fragment and where it goes; never write the
# harness config ourselves.
emit_hooks() { # $1 = harness, $2 = target, rest = event names
  "$PY" - "$RECORD" "$1" "$2" "${@:3}" <<'PY'
import json, sys
record, harness, target, events = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
entry = {"matcher": "", "hooks": [
    {"type": "command", "command": f"python3 {record} --harness {harness}", "timeout": 10}]}
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
    emit_hooks claude_code "~/.claude/settings.json (or .claude/settings.json for this repo only)" PostToolUse PostToolUseFailure
    ;;
  codex)
    emit_hooks codex "~/.codex/hooks.json" PostToolUse
    cat <<'EOF'

Run `/hooks` in Codex to review and trust the new hook (Codex skips untrusted
hooks) before restarting it.
EOF
    ;;
  cursor)
    "$PY" - "$RECORD" <<'PY'
import json, sys
command = f"python3 {sys.argv[1]} --harness cursor"
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
    $0 hermes | claude_code | codex | cursor | none
EOF
    ;;
esac

cat <<EOF

Nothing here is readable until calls accumulate. Check with:
    $PY $SKILL_DIR/report.py
EOF
