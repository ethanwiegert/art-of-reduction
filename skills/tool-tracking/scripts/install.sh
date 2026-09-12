#!/usr/bin/env bash
# One-shot setup for the tool-call log.
#
#   ./install.sh                 # create the store + print the hook block
#   ./install.sh hermes          # ... and write a ready-to-paste snippet
#   ./install.sh claude_code     # ... and emit a merged settings file
#   ./install.sh codex
#   ./install.sh cursor
#   ./install.sh none            # no native hook: env vars for a custom wrapper
#
# Idempotent: re-running never drops data and never overwrites an existing
# config file - it writes next to it and prints the merge line.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"      # .../tool-tracking/scripts
ROOT="$(cd "$SKILL_DIR/.." && pwd)"             # .../tool-tracking
AOR_HOME="${AOR_HOME:-$HOME/.art-of-reduction}"
HARNESS="${1:-print}"
DB="$AOR_HOME/tool-tracking.db"
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
chmod +x "$ROOT/hooks/"*.sh "$SKILL_DIR/"*.py

hook_block() {
  cat <<EOF
hooks:
  post_tool_call:
    - matcher: ".*"
      command: "$PY $ROOT/hooks/hermes.sh"
      timeout: 10
EOF
}

emit_json() { # $1 = harness, $2 = script
  "$PY" - "$ROOT/hooks/$2" "$AOR_HOME/hook.$1.json" <<'PY'
import json, sys
script, out = sys.argv[1], sys.argv[2]
doc = {"PostToolUse": [{"matcher": "", "hooks": [
    {"type": "command", "command": script, "timeout": 10}]}]}
if "codex" in out:
    doc = {"description": "Record every tool call into the shared art-of-reduction log.",
           "hooks": doc}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
print(out)
PY
}

case "$HARNESS" in
  hermes)
    SCRIPT="$ROOT/hooks/hermes.sh"
    mkdir -p "$HOME/.hermes/agent-hooks"
    ln -sf "$SCRIPT" "$HOME/.hermes/agent-hooks/aor-record.sh"
    hook_block > "$AOR_HOME/hermes-hooks.snippet.yaml"
    cat <<EOF
Wrote $AOR_HOME/hermes-hooks.snippet.yaml

Merge those lines under the existing \`hooks:\` key in ~/.hermes/config.yaml,
then restart Hermes. The first tool call raises a one-time consent prompt for
the hook - approve it and that is the whole setup.
EOF
    ;;
  claude_code)
    out="$(emit_json claude_code claude-code.sh)"
    cat <<EOF
Wrote $out

Merge its PostToolUse entry into the "hooks" object of ~/.claude/settings.json
(project-wide) or .claude/settings.json (this repo only):
    python3 - <<'PY'
    import json, pathlib
    target, add = pathlib.Path.home()/".claude/settings.json", json.load(open("$out"))
    target.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(target.read_text()) if target.exists() else {}
    cfg.setdefault("hooks", {}).setdefault("PostToolUse", []).extend(add["PostToolUse"])
    target.write_text(json.dumps(cfg, indent=2))
    PY
EOF
    ;;
  codex)
    out="$(emit_json codex codex.sh)"
    cat <<EOF
Wrote $out

Run \`/hooks\` in Codex to review and trust the new hook (Codex skips untrusted
hooks), or merge the entry into ~/.codex/hooks.json yourself.
EOF
    ;;
  cursor)
    "$PY" - "$AOR_HOME/hook.cursor.json" <<PY
import json, pathlib, sys
template = json.load(open("$ROOT/hooks/cursor.json"))
template["hooks"]["postToolUse"] = [{"command": "$ROOT/hooks/cursor.sh"}]
dest = pathlib.Path(sys.argv[1])
dest.write_text(json.dumps(template, indent=2) + "\n")
print(dest)
PY
    cat <<EOF

Copy it to .cursor/hooks.json in the project (or ~/.cursor/hooks.json for all
projects). Cursor resolves relative command paths against the hooks.json file,
so the absolute path above is what you want.
EOF
    ;;
  none)
    cat <<EOF
No native hook needed. Point your wrapper at record.py and it will map the
payload automatically:

    export AOR_HARNESS=your_harness      # or: record.py --harness your_harness
    export AOR_HOME="$AOR_HOME"
    # every tool call:  printf '%s' "\$PAYLOAD" | $PY $SKILL_DIR/scripts/record.py

If a synchronous write ever shows up in your latency, set AOR_RECORD_MODE=jsonl
to append instead of inserting, then drain the queue when idle:
    $PY $SKILL_DIR/scripts/report.py import
EOF
    ;;
  *)
    hook_block
    cat <<EOF

Pass a harness name to write the config for it:
    $0 hermes | claude_code | codex | cursor | none
EOF
    ;;
esac

cat <<EOF

Nothing here is readable until calls accumulate. Check with:
    $PY $SKILL_DIR/scripts/report.py
EOF
