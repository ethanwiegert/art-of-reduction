#!/usr/bin/env python3
"""Shared ingest endpoint: many agents, one tool-call log.

record.py is a per-machine hook. This serves the same mapping and redaction
over HTTP, so a team's harnesses POST to one store instead of each keeping
their own. Claude Code calls it natively with a `type: "http"` hook.

    python3 serve.py                      # 127.0.0.1:8787, prints the hook fragment
    python3 serve.py --host 0.0.0.0 --port 8787

    POST /hook/<harness>   body = the harness's hook JSON   -> 204

Environment:
    AOR_HOME          store directory (default ~/.art-of-reduction)
    AOR_INGEST_TOKEN  if set, requests need `Authorization: Bearer <token>`
    AOR_TRUNCATE      max characters kept per input/output field (default 2000)

Stdlib only. Redaction happens here, before anything touches disk, so a client
can never opt out of it. Every refusal is a non-2xx, which Claude Code treats
as a non-blocking error: the agent never waits on or breaks because of this.
"""
from __future__ import annotations

import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record  # noqa: E402

MAX_BODY = 1 << 20  # a hook payload is truncated to 2000 chars per field anyway
TOKEN = os.environ.get("AOR_INGEST_TOKEN", "")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if len(parts) != 2 or parts[0] != "hook" or not parts[1]:
            return self.send_error(404, "POST /hook/<harness>")
        if TOKEN and not hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {TOKEN}"
        ):
            return self.send_error(401)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.send_error(400, "bad Content-Length")
        if length > MAX_BODY:
            return self.send_error(413)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send_error(400, "body must be JSON")
        if not isinstance(payload, dict):
            return self.send_error(400, "body must be a JSON object")
        record.write(record.map_row(payload, parts[1]))
        self.send_response(204)
        self.end_headers()

    def log_request(self, code="-", size="-"):  # one line per tool call is noise
        if not 200 <= int(code) < 300:
            super().log_request(code, size)


def fragment(url: str) -> str:
    hook = {"type": "http", "url": f"{url}/hook/claude_code", "timeout": 5}
    if TOKEN:
        hook["headers"] = {"Authorization": "Bearer $AOR_INGEST_TOKEN"}
        hook["allowedEnvVars"] = ["AOR_INGEST_TOKEN"]
    entry = [{"matcher": "", "hooks": [hook]}]
    return json.dumps({"PostToolUse": entry, "PostToolUseFailure": entry}, indent=2)


def main(argv: list) -> None:
    host, port = "127.0.0.1", 8787
    for index, arg in enumerate(argv[:-1]):
        if arg == "--host":
            host = argv[index + 1]
        elif arg == "--port":
            port = int(argv[index + 1])
    if host not in {"127.0.0.1", "localhost"} and not TOKEN:
        sys.exit("refusing to listen beyond localhost without AOR_INGEST_TOKEN")
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    print('Merge under "hooks" in each agent\'s ~/.claude/settings.json'
          " (swap in the address agents reach this host on):\n")
    print(fragment(url))
    print(f"\nstore: {record.DB_PATH}\nlistening: {url}/hook/<harness>", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
