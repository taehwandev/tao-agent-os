from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.claude_ask_override_notice import (
    gate_overriding_ask_rules,
    notice_claude_ask_overrides,
)


def settings_with_ask(*rules: object) -> dict:
    return {"permissions": {"allow": ["Bash(git stash:*)"], "ask": list(rules)}}


class GateOverridingAskRulesTest(unittest.TestCase):
    def test_matches_every_spelling_of_an_ordinary_subcommand(self) -> None:
        rules = [
            "Bash(git rebase:*)",
            "Bash(git -C * rebase)",
            "Bash(git -C * stash *)",
            "Bash(git merge *)",
            "Bash(git reset:*)",
        ]

        self.assertEqual(gate_overriding_ask_rules(settings_with_ask(*rules)), rules)

    def test_a_wildcard_subcommand_overrides_all_of_them(self) -> None:
        self.assertEqual(
            gate_overriding_ask_rules(settings_with_ask("Bash(git *)", "Bash(git -C * *)")),
            ["Bash(git *)", "Bash(git -C * *)"],
        )

    def test_ignores_rules_the_gate_does_not_approve(self) -> None:
        settings = settings_with_ask(
            "Bash(git log:*)",
            "Bash(git filter-branch *)",
            "Bash(gitk *)",
            "Bash(rm -rf *)",
            "Edit(//etc/**)",
            "Bash(git)",
            "Bash(git -C *)",
            7,
        )

        self.assertEqual(gate_overriding_ask_rules(settings), [])

    def test_only_ask_rules_count(self) -> None:
        self.assertEqual(gate_overriding_ask_rules({"permissions": {"allow": ["Bash(git rebase:*)"]}}), [])
        self.assertEqual(gate_overriding_ask_rules({"permissions": {"ask": "Bash(git rebase:*)"}}), [])
        self.assertEqual(gate_overriding_ask_rules({}), [])


class NoticeClaudeAskOverridesTest(unittest.TestCase):
    def _notice(self, content: str | None) -> tuple[list[str], str, str | None]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                rules = notice_claude_ask_overrides(path)
            after = path.read_text(encoding="utf-8") if path.exists() else None
        return rules, stderr.getvalue(), after

    def test_reports_overriding_rules_without_editing_the_file(self) -> None:
        content = json.dumps(settings_with_ask("Bash(git -C * rebase *)", "Bash(git log:*)"))

        rules, stderr, after = self._notice(content)

        self.assertEqual(rules, ["Bash(git -C * rebase *)"])
        self.assertIn("Claude notice:", stderr)
        self.assertIn("Bash(git -C * rebase *)", stderr)
        self.assertNotIn("Bash(git log:*)", stderr)
        self.assertEqual(after, content)

    def test_stays_silent_when_nothing_overrides(self) -> None:
        rules, stderr, _after = self._notice(json.dumps(settings_with_ask("Bash(git log:*)")))

        self.assertEqual((rules, stderr), ([], ""))

    def test_missing_or_unreadable_settings_never_fail_setup(self) -> None:
        for content in (None, "{not json", "[]"):
            with self.subTest(content=content):
                self.assertEqual(self._notice(content)[:2], ([], ""))

    def test_claude_setup_reports_the_rule_and_keeps_it(self) -> None:
        from support.claude_setup import configure_claude

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"permissions": {"ask": ["Bash(git stash:*)"]}}))
            stderr = StringIO()
            with patch("support.claude_setup.Path.home", return_value=home), redirect_stderr(stderr):
                configure_claude(
                    False, root=ROOT, scripts_dir=ROOT / "scripts",
                    launcher_path=home / "bin" / "tao-hook", spill_available=False,
                )

            self.assertIn("Bash(git stash:*)", stderr.getvalue())
            self.assertEqual(
                json.loads(settings.read_text())["permissions"]["ask"], ["Bash(git stash:*)"]
            )


if __name__ == "__main__":
    unittest.main()
