-- art-of-reduction tool-call log.
-- Applied by record.py (and so by install.sh) whenever PRAGMA user_version is
-- behind; record.py also adds columns a store created before them is missing.
-- Safe to re-run: everything here is IF NOT EXISTS.
--
-- Column notes:
--   ts          UTC ISO-8601 with milliseconds, e.g. 2026-09-11T21:04:05.123Z
--   session_id  harness session/thread id; opaque, '' when the harness has none
--   harness     which agent wrote the row: claude_code | codex | cursor | gemini | copilot | hermes | ...
--   cwd         the agent's working directory, '' when the payload has none
--   tool        harness tool name; 'unknown' when the payload carries none
--   tool_input  JSON-encoded arguments, redacted then truncated
--   tool_output JSON-encoded (or raw) result, redacted then truncated
--   status      'success' | 'error' | 'unknown'
--   duration_ms NULL when the harness does not report a duration
--   input_chars, output_chars  length before truncation: what the call put into
--               the model's context. NULL on rows recorded before they existed.
--
-- One row per tool call, from every harness that shares this database, which is
-- why session_id and harness are separate columns.

-- Several harnesses write while report.py reads; WAL keeps readers from blocking writers.
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY,
    ts          TEXT    NOT NULL,
    session_id  TEXT    NOT NULL DEFAULT '',
    harness     TEXT    NOT NULL,
    cwd         TEXT    NOT NULL DEFAULT '',
    tool        TEXT    NOT NULL,
    tool_input  TEXT    NOT NULL DEFAULT '',
    tool_output TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'unknown',
    duration_ms INTEGER,
    input_chars  INTEGER,
    output_chars INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_tool    ON tool_calls (tool);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls (session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts      ON tool_calls (ts);
CREATE INDEX IF NOT EXISTS idx_tool_calls_status  ON tool_calls (status);
