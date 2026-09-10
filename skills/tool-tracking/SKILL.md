---
name: tool-tracking
description: Use on setup of the art-of-reduction skills to add data tracking and metrics to tool usage.
---

# Instructions

Ask a clarifying question for the user on what local database they prefer, suggest sqlite.  Once you have an answer verify the database does not already exist, and if not make `tool-tracking.db` in an `art-of-reduction` directory.  Check what table exists if it is pre-existing.  We want to make a table with a primary key ID, date_posted, session_id, harness, tool, tool_input, and tool_ouput.  Ensure that this can be reached by other harnesses beyond yours, do not setup in your `.harness` folder.  Set up a simple pre-tool hook for yourself that will just run a simple insert on every tool usage.  Don't add additional logic or wrap it in messaging or responses, ensure it's backend changes only (and harness should be hardset to what you are (codex, claude_code etc.)).  Run `tool-dashboard` when complete.