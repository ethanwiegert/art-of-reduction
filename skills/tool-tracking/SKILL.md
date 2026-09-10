---
name: tool-tracking
description: Use on setup of the art-of-reduction skills to add data tracking and metrics to tool usage.
---

# Instructions

Ask a clarifying question for the user on what local database they prefer, suggest sqlite. Once you have an answer verify the database does not already exist, and if not make `tool-tracking.db` in `~/.art-of-reduction/`. Check what tables exist if it is pre-existing. We want to make a `tool_calls` table with a primary key ID, timestamp, session_id, harness, tool, tool_input, tool_output, and status. Ensure that this can be reached by other harnesses beyond yours, do not set up in your `.harness` folder. Set up a simple post-tool hook for yourself that will just run a simple insert on every tool usage, on both successful and failed calls (the status column records which). Don't add additional logic or wrap it in messaging or responses, ensure it's backend changes only (and harness should be hardset to what you are (codex, claude_code etc.)). If your harness doesn't support tool hooks, instead write a simple sync script that reads your harness's native session history into the same table. Run `tool-dashboard` when complete.