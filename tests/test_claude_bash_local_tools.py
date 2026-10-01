"""Local Node test runs and pure lookups classify like the Python test runners."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_claude_temp_checkout_scratch import _Fixture
import claude_bash_local_tools as local_tools
import claude_bash_readonly as readonly
import claude_pretool_gate as gate


class NodeTestAndLookupClassification(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.other = self.base / "home" / "other"
        self._governed_repository(self.other)
        (self.project / "tsconfig.json").write_text("{}\n")
        self.scratch = self.temp / "scratch-out"
        self.scratch.mkdir()

    def _kind(self, command: str, cwd: Path | None = None) -> str:
        payload = {"tool_input": {"command": command}}
        effective, tokens, simple = readonly.bash_invocation(payload, cwd or self.project)
        return readonly.bash_command_kind(tokens, simple, effective)

    def test_local_node_test_and_typecheck_runs_are_read_only(self) -> None:
        for command in (
            "npm test",
            "npm run test",
            "npm run-script test",
            "npm t",
            "npm test --silent",
            "npm test -- --coverage",
            "npm test -- src/app.test.ts",
            "npx tsc --noEmit",
            "npx tsc --noEmit -p .",
            "npx --no-install tsc --noEmit --project tsconfig.json",
            "tsc --noEmit --pretty",
            "npm test | tail -5",
            f"cd {self.project} && npm test",
            "npm test && npx tsc --noEmit",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command))

    def test_node_runs_that_emit_or_leave_the_project_stay_mutating(self) -> None:
        for command in (
            "npx tsc",
            "npx tsc -p .",
            "npx tsc --noEmit false",
            "npx tsc --noEmit --outDir dist",
            "npx tsc --noEmit --init",
            f"npx tsc --noEmit -p {self.other}",
            "npm run build",
            "npm run test:unit",
            "npm install",
            "npx eslint .",
            f"npm test -- {self.other}",
            f"npm test -- --outputFile={self.other / 'out.json'}",
            f"npm test --prefix {self.other}",
            f"npm --prefix {self.other} test",
            f"echo ready && cd {self.other} && npm test",
            "npm ls && npm run build",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self._kind(command))

    def test_node_test_without_a_known_directory_is_not_admitted(self) -> None:
        self.assertEqual("mutating", local_tools.node_test_kind(["npm", "test"], None))
        self.assertIsNone(local_tools.node_test_kind(["npx", "tsc"], self.project))

    def test_pure_lookups_are_read_only(self) -> None:
        for command in (
            "npm view @scope/pkg version",
            "npm info left-pad --json",
            "npm whoami",
            "npm ls",
            "npm ls --depth=0",
            'graphify query "push command" --budget 200',
            'graphify path "A" "B" --graph graphify-out/graph.json',
            'graphify explain "X"',
            "defaults read /Applications/Spill.app/Contents/Info.plist CFBundleShortVersionString",
            "defaults -currentHost read com.apple.dock",
            "defaults read-type com.apple.dock tilesize",
            "footprint -p 18008",
            f"footprint -p 18008 -j {self.scratch / 'fp.json'}",
            "top -l 1 -pid 18008",
            "top -l1 -stats pid,mem",
            "sample 61464 30",
            f"sample 61464 30 -file {self.scratch / 'sample.txt'}",
            "npm view left-pad version | head -1",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command))

    def test_lookup_neighbours_that_write_or_wait_stay_mutating(self) -> None:
        for command in (
            "npm publish",
            f"npm view left-pad --logs-dir={self.other}",
            f"npm ls --cache {self.other}",
            "graphify update .",
            "graphify query x --out result.json",
            "defaults write com.x key value",
            "defaults delete com.x",
            "defaults import com.x plist",
            f"footprint -p 1 -j {self.other / 'fp.json'}",
            "footprint -p 1 --json fp.json",
            "top",
            "top -pid 1",
            "top -l 0",
            "sample 61464 30 -e",
            f"sample 61464 30 -file {self.other / 'sample.txt'}",
            f"sample 61464 30 -file {self.project / 'sample.txt'}",
            "sample 61464 30 -file",
            "sample",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self._kind(command))

    def test_gate_keeps_node_runs_into_another_project_governed(self) -> None:
        for command in (
            f"npm test -- {self.project}",
            f"npx tsc --noEmit -p {self.project}",
            f"echo ready && cd {self.project} && npm test",
            f"sample 1 5 -file {self.project / 'sample.txt'}",
        ):
            with self.subTest(command=command):
                # The compound line cannot be read, so it asks instead.
                self.assertEqual(
                    "ask" if "&&" in command else "deny",
                    self._bash(command, cwd=self.bench),
                )

    def test_gate_scope_reads_the_measured_commands_as_read_only(self) -> None:
        """The gate allows a read_only scope before any run or worktree check."""

        def scope_kind(command: str) -> str:
            payload = {"tool_name": "Bash", "tool_input": {"command": command}}
            return gate._call_scope(payload, "Bash", self.project).bash_kind

        for command in (
            "npm test", "npm run test", "npx tsc --noEmit -p .", "npm view @scope/pkg version",
            "npm whoami", "npm ls", 'graphify query "push command" --budget 200',
            "defaults read /Applications/Spill.app/Contents/Info.plist CFBundleShortVersionString",
            "footprint -p 18008", "top -l 1 -pid 18008",
            f"sample 61464 30 -file {self.scratch / 'sample.txt'}",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", scope_kind(command))
        for command in ("npx tsc", "npm run build", "defaults write com.x k v", "gh pr merge 1"):
            with self.subTest(command=command):
                self.assertIn(scope_kind(command), {"mutating", "unknown"})


if __name__ == "__main__":
    unittest.main()
