"""Real local HTTP execution and workflow transition, without service credentials."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("curl"), "curl required for local execution check")
class PretoolExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name) / "project"
        self.project.mkdir()
        (self.project / "AGENTS.md").write_text("Uses tao-hook.\n")
        (self.project / ".gitignore").write_text(".tao/\n")
        self.environment = dict(os.environ)
        for key in ("CODEX_THREAD_ID", "TAO_WORKER_EVIDENCE", "TAO_PARENT_EVIDENCE_READONLY"):
            self.environment.pop(key, None)
        self.environment.update(TAO_STATE_HOME=str(Path(self.directory.name) / "state"),
                                TAO_PRETOOL_RUNTIME="claude", CLAUDE_CODE_SESSION_ID="execution-test")
        self.run_command(["git", "init", "-q"])
        self.run_command(["git", "add", "AGENTS.md", ".gitignore"])
        self.run_command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                          "commit", "-qm", "fixture"])

    def run_command(self, args, **kwargs):
        return subprocess.run(args, cwd=self.project, env=self.environment,
                              capture_output=True, text=True, timeout=30, **kwargs)

    def decision(self, argv):
        payload = {"tool_name": "Bash", "cwd": str(self.project),
                   "session_id": "execution-test", "tool_input": {"command": argv if isinstance(argv, str) else shlex.join(argv)}}
        result = self.run_command([sys.executable, str(ROOT / "scripts/claude_pretool_gate.py")],
                                  input=json.dumps(payload))
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None

    def start(self, read_only=False):
        args = [sys.executable, str(ROOT / "scripts/agent-hook.py"), "start",
                "--project", str(self.project), "--rules", str(ROOT), "--command", "bugfix",
                "--request", "Inspect fixture only" if read_only else "Apply the authorized fixture correction",
                "--intent", "inspect_fixture" if read_only else "correct_fixture",
                "--target-summary", "Local integration fixture", "--runtime-session-id", "execution-test"]
        if read_only:
            args.append("--read-only")
        result = self.run_command(args)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_read_then_real_authorized_write_transition_and_http_execution(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append((self.command, self.headers.get("Authorization") == "Bearer test-only"))
                body = json.dumps({"method": self.command, "authenticated": observed[-1][1]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        headers = self.project / "headers.txt"
        headers.write_text("Authorization: Bearer test-only\n")
        url = f"http://127.0.0.1:{server.server_port}/events"
        read = ["curl", "-q", "--noproxy", "*", "-sS", "-H", "@" + str(headers), url]
        write = ["curl", "-q", "--noproxy", "*", "-sS", "-X", "POST", url]
        self.assertIsNone(self.decision(read), "A cold lookup must not require a workflow")
        result = self.run_command(read)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"method": "GET", "authenticated": True}, json.loads(result.stdout))
        self.assertNotIn("test-only", result.stdout + result.stderr)
        self.assertEqual("deny", self.decision(write)["permissionDecision"])
        self.start(read_only=True)
        self.assertIsNone(self.decision(read))
        self.assertEqual("deny", self.decision(write)["permissionDecision"])
        self.start(read_only=False)
        self.assertIsNone(self.decision(write), "The prior read-only run must not veto the later scoped write")
        result = self.run_command(write)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("POST", json.loads(result.stdout)["method"])
        self.assertEqual([("GET", True), ("POST", False)], observed)

    def test_unknown_is_diagnosed_and_valid_read_retry_needs_no_task_state(self):
        denied = self.decision(["curl", "https://example.invalid"])
        self.assertEqual("deny", denied["permissionDecision"])
        self.assertIn("effect: unknown", denied["permissionDecisionReason"])
        self.assertIn("put -q first", denied["permissionDecisionReason"])
        self.assertIsNone(self.decision(["curl", "-q", "https://example.invalid"]))
        self.assertFalse((self.project / ".tao" / "runs").exists())

    def test_multiline_reads_need_no_run_but_writes_still_need_authority(self):
        self.assertIsNone(self.decision('git status --short\ncat AGENTS.md'))
        self.assertIsNone(self.decision("rg 'first\nsecond' AGENTS.md"))
        self.assertFalse((self.project / '.tao' / 'runs').exists())
        for command in ('git status --short\ntouch result',
                        'cat AGENTS.md\ncat AGENTS.md > result',
                        'cat $\\\n(touch result)'):
            with self.subTest(command=command):
                self.assertEqual('deny', self.decision(command)['permissionDecision'])

    def test_deployment_status_read_needs_no_run_or_new_start(self):
        endpoint = 'repos/example/project/commits/abc123/status'
        query = '{state: .state, statuses: [.statuses[] | {context,state,description,target_url}]}'
        for method in ([], ['--method', 'GET']):
            self.assertIsNone(self.decision(['gh', 'api', *method, endpoint, '--jq', query]))
        self.assertIsNone(self.decision('git status --short; gh api ' + endpoint))
        self.assertFalse((self.project / '.tao' / 'runs').exists())
        for args in (['--method', 'POST'], ['-f', 'state=success'], ['--cache', '1h'],
                     ['--method', 'GET', '--input', 'payload.json']):
            self.assertEqual('deny', self.decision(['gh', 'api', endpoint, *args])['permissionDecision'])
