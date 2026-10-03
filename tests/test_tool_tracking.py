"""Tests for the tool-tracking hook, report, and installer. Stdlib only."""
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "skills" / "tool-tracking"
RECORD = TOOL / "scripts/record.py"
REPORT = TOOL / "scripts/report.py"
INSTALL = TOOL / "scripts/install.sh"
SERVE = TOOL / "scripts/serve.py"
SCHEMA = TOOL / "schema.sql"
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def run_record(payload, harness, home, truncate=None):
    env = {**os.environ, "AOR_HOME": str(home)}
    if truncate is not None:
        env["AOR_TRUNCATE"] = str(truncate)
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(RECORD), "--harness", harness],
                          input=body, capture_output=True, text=True, env=env)


def read_rows(home):
    con = sqlite3.connect(str(home / "tool-tracking.db"))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM tool_calls ORDER BY id")]
    con.close()
    return rows


class TempHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class RecordTests(TempHome):
    def test_status_per_harness(self):
        cases = [
            ("claude_code", {"hook_event_name": "PostToolUse", "tool_name": "Bash"}, "success"),
            ("claude_code", {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": "x"}, "error"),
            ("codex", {"hook_event_name": "PostToolUse", "tool_name": "shell"}, "unknown"),
            ("cursor", {"tool_name": "read_file", "duration": 42}, "success"),
            ("cursor", {"tool_name": "write_file", "error_message": "no"}, "error"),
            ("hermes", {"tool_name": "terminal", "status": "success"}, "success"),
            ("hermes", {"tool_name": "terminal", "status": "error"}, "error"),
        ]
        for harness, payload, expected in cases:
            with self.subTest(harness=harness, status=expected):
                out = run_record(payload, harness, self.home)
                self.assertEqual((out.returncode, out.stdout.strip()), (0, "{}"))
                self.assertEqual(read_rows(self.home)[-1]["status"], expected)

    def test_session_id_duration_and_ts(self):
        run_record({"conversation_id": "conv-1", "tool_name": "read_file", "duration": 42}, "cursor", self.home)
        run_record({"session_id": "sess-1", "hook_event_name": "PostToolUse", "tool_name": "Bash"}, "claude_code", self.home)
        rows = read_rows(self.home)
        self.assertEqual((rows[0]["session_id"], rows[0]["duration_ms"]), ("conv-1", 42))
        self.assertEqual(rows[1]["session_id"], "sess-1")
        self.assertIsNone(rows[1]["duration_ms"])
        self.assertTrue(TS.match(rows[0]["ts"]), rows[0]["ts"])

    def test_non_json_stdin(self):
        out = run_record("not json", "hermes", self.home)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "{}"))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_redaction_and_truncation(self):
        text = "Authorization: Bearer abcdefghijklmnop API_KEY=supersecretvalue tail"
        run_record({"tool_name": "Bash", "tool_input": text}, "claude_code", self.home)
        blob = read_rows(self.home)[0]["tool_input"]
        self.assertNotIn("abcdefghijklmnop", blob)
        self.assertNotIn("supersecretvalue", blob)
        run_record({"tool_name": "Bash", "tool_input": "x" * 500}, "claude_code", self.home, truncate=10)
        self.assertEqual(read_rows(self.home)[1]["tool_input"], "x" * 10)


class ReportTests(TempHome):
    def test_repeats_and_help(self):
        con = sqlite3.connect(str(self.home / "tool-tracking.db"))
        con.executescript(SCHEMA.read_text())
        con.executemany(
            "INSERT INTO tool_calls (ts, session_id, harness, tool, tool_input, status)"
            " VALUES ('2026-09-12T00:00:00.000Z', ?, 'hermes', 'read', ?, 'success')",
            [("sess-a", "same input"), ("sess-a", "same input"),
             ("sess-b", "same input"), ("sess-b", "lonely input")],
        )
        con.commit()
        con.close()
        repeats = subprocess.run(
            [sys.executable, str(REPORT), "repeats"], capture_output=True, text=True,
            env={**os.environ, "AOR_HOME": str(self.home)},
        )
        self.assertEqual(repeats.returncode, 0, repeats.stderr)
        self.assertIn("same input", repeats.stdout)
        self.assertNotIn("lonely", repeats.stdout)
        helped = subprocess.run(
            [sys.executable, str(REPORT), "--help"], capture_output=True, text=True,
            env={**os.environ, "AOR_HOME": str(self.home / "absent")},
        )
        self.assertEqual(helped.returncode, 0, helped.stderr)
        self.assertIn("Read-only", helped.stdout)
        limited = subprocess.run(
            [sys.executable, str(REPORT), "--limit", "5"], capture_output=True,
            text=True, env={**os.environ, "AOR_HOME": str(self.home)},
        )
        self.assertEqual(limited.returncode, 0, limited.stderr)

    def test_kinds_fold_across_harnesses(self):
        con = sqlite3.connect(str(self.home / "tool-tracking.db"))
        con.executescript(SCHEMA.read_text())
        con.executemany(
            "INSERT INTO tool_calls (ts, session_id, harness, tool, tool_input, status)"
            " VALUES ('2026-09-12T00:00:00.000Z', ?, ?, ?, ?, 'success')",
            [("sess-a", "claude_code", "Bash", '{"command": "npm test"}'),
             ("sess-b", "cursor", "Shell", '{"command": "npm test"}'),
             ("sess-c", "hermes", "terminal", '{"command": "npm test"}'),
             ("sess-d", "claude_code", "Read", '{"file": "x"}')],
        )
        con.commit()
        con.close()
        env = {**os.environ, "AOR_HOME": str(self.home)}
        repeats = subprocess.run(
            [sys.executable, str(REPORT), "repeats"], capture_output=True, text=True, env=env,
        ).stdout
        shell = [line for line in repeats.splitlines() if line.startswith("shell")]
        self.assertEqual(len(shell), 1)
        self.assertEqual(shell[0].split()[1:4], ["3", "3", "3"])
        self.assertNotIn("Bash", repeats)
        self.assertNotIn("Shell", repeats)
        tools = subprocess.run(
            [sys.executable, str(REPORT), "tools"], capture_output=True, text=True, env=env,
        ).stdout
        shell = [line for line in tools.splitlines() if line.startswith("shell")]
        self.assertEqual(len(shell), 1)
        self.assertEqual(shell[0].split()[1], "3")


class InstallTests(TempHome):
    def test_fragment_and_store(self):
        for harness in ("hermes", "claude_code", "codex", "cursor"):
            with self.subTest(harness=harness):
                home = self.home / harness
                home.mkdir()
                out = subprocess.run(
                    ["bash", str(INSTALL), harness], capture_output=True, text=True,
                    env={**os.environ, "AOR_HOME": str(home)},
                )
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn(f"{RECORD} --harness {harness}", out.stdout)
                self.assertTrue((home / "tool-tracking.db").exists())
                self.assertEqual([p.name for p in home.iterdir()], ["tool-tracking.db"])


class ServeTests(TempHome):
    def setUp(self):
        super().setUp()
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVE), "--port", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env={**os.environ, "AOR_HOME": str(self.home), "AOR_INGEST_TOKEN": "t0k"},
        )
        lines = []
        for line in self.proc.stdout:
            lines.append(line)
            if line.startswith("listening:"):
                self.url = line.split()[1].rsplit("/hook", 1)[0]
                break
        self.banner = "".join(lines)

    def tearDown(self):
        self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()
        super().tearDown()

    def post(self, path, body, token="t0k"):
        req = urllib.request.Request(self.url + path, data=body, method="POST")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as err:
            return err.code

    def test_claude_code_http_hook(self):
        payload = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                   "tool_input": {"command": "gh pr checks 12 --token ghp_abcdefghijklmnop"}}
        self.assertEqual(self.post("/hook/claude_code", json.dumps(payload).encode()), 204)
        row = read_rows(self.home)[0]
        self.assertEqual((row["harness"], row["tool"], row["session_id"], row["status"]),
                         ("claude_code", "Bash", "s1", "success"))
        self.assertIn("gh pr checks", row["tool_input"])
        self.assertNotIn("ghp_abcdefghijklmnop", row["tool_input"])

    def test_refusals_write_nothing(self):
        self.assertEqual(self.post("/hook/claude_code", b"{}", token=None), 401)
        self.assertEqual(self.post("/hook/claude_code", b"{}", token="wrong"), 401)
        self.assertEqual(self.post("/elsewhere", b"{}"), 404)
        self.assertEqual(self.post("/hook/claude_code", b"not json"), 400)
        self.assertEqual(self.post("/hook/claude_code", b"[1]"), 400)
        self.assertFalse((self.home / "tool-tracking.db").exists())

    def test_banner_prints_hook_fragment(self):
        self.assertIn('"type": "http"', self.banner)
        self.assertIn("/hook/claude_code", self.banner)
        self.assertIn("Bearer $AOR_INGEST_TOKEN", self.banner)
