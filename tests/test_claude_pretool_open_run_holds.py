"""False holds and false entry denials found in a week of real transcripts.

An open run held every line the segment reader could not read as a possible
publication, and the read-only classifier treated `2>&1`, `sleep` and
`git branch --sort` as writes. Each case below is a shape that was refused;
each held case is one an existing test already requires to stay held.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from claude_bash_readonly import bash_command_kind, bash_invocation  # noqa: E402
from claude_pretool_publication import open_run_publication_hold, publication_hold  # noqa: E402


class OpenRunPublicationHoldTests(unittest.TestCase):
    # Shapes of commands an open run refused, shortened.
    RELEASED = (
        "(swift test 2>&1 | tail -40)",
        "cd ~/git/app && (nohup npm run dev > /tmp/dev.log 2>&1 &)",
        "cat >> docs/ard.md <<'EOF'\n\n## Settings Structure\n\nPersistence owner: `Settings` only.\nEOF",
        'pgrep -fl "Spill.app" || (rm -rf /Applications/Spill.app && ditto .build/Spill.app /Applications/Spill.app)',
        "cd app && git merge-base HEAD feature && (git diff --name-only HEAD | head)",
    )
    # Every line an existing test requires `publication_hold` to call unreadable.
    STILL_HELD = (
        'eval "$cmd"',
        'bash -c "$cmd"',
        'sh -c "$cmd"',
        "$(echo git) push",
        "for u in a; do $cmd push; done",
        "for u in a; do `echo git` push; done",
        "git $action origin",
        "nice git push origin work",
        "nice -n 5 git push origin work",
        "timeout 30 git push origin work",
        "sudo git push origin work",
        "xargs git push",
        "! (git push origin work)",
        "(git push origin work)",
        "{ git push origin work; }",
        "case x in x) git push;; esac",
        "echo `git push`",
        "echo x > >(git push)",
        "$cmd > $OUT",
        "cat refs | xargs git push",
        "echo push | xargs git",
        "xargs -I{} git {} < commands.txt",
        "xargs --replace=X git X < commands.txt",
        'xargs sh -c "$x"',
        "xargs $tool",
    )

    def test_an_unreadable_line_that_names_no_publication_runs(self) -> None:
        for command in self.RELEASED:
            with self.subTest(command=command):
                self.assertEqual("unreadable", publication_hold(command))
                self.assertEqual("", open_run_publication_hold(command))

    def test_a_line_that_could_hide_a_publication_stays_held(self) -> None:
        for command in self.STILL_HELD:
            with self.subTest(command=command):
                self.assertTrue(open_run_publication_hold(command))

    def test_a_readable_publication_is_unchanged(self) -> None:
        for command in ("git push origin main", "cd x && git push", "gh release create v1"):
            with self.subTest(command=command):
                self.assertEqual("publishes", open_run_publication_hold(command))


def _kind(command: str) -> str:
    cwd, tokens, simple = bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
    return bash_command_kind(tokens, simple, cwd)


class ReadOnlyFalseWriteTests(unittest.TestCase):
    def test_sleep_and_descriptor_duplication_are_not_writes(self) -> None:
        for command in (
            "sleep 2; pgrep -fl Spill || echo none",
            "git status --short 2>&1 | wc -l",
            "git log --oneline -5 2>&1",
        ):
            with self.subTest(command=command):
                self.assertNotEqual("mutating", _kind(command))

    def test_a_duplication_to_a_file_is_still_a_write(self) -> None:
        self.assertEqual("mutating", _kind("echo x 2>&out.txt"))

    def test_branch_display_options_list_rather_than_create(self) -> None:
        for command in (
            "git branch -a --sort=-committerdate --format=%(refname:short)",
            "git branch --sort committerdate",
            "git branch --format=%(refname:short) --no-color",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", _kind(command))
        for command in ("git branch --sort=x newname", "git branch --format=x feature"):
            with self.subTest(command=command):
                self.assertEqual("mutating", _kind(command))


@unittest.skipUnless(
    (Path.home() / "Library/Application Support/Spill/adapters/setup/spill-token-metering-setup.mjs").is_file(),
    "the Spill label helper is not installed here",
)
class SpillLabelChainTests(unittest.TestCase):
    LABEL = (
        "node ~/Library/Application\\ Support/Spill/adapters/setup/spill-token-metering-setup.mjs "
        "--label claude --task-type debugging --stage implement --if-absent"
    )

    def test_the_label_helper_with_redirected_output_chains_into_reads(self) -> None:
        command = f"{self.LABEL} >/dev/null 2>&1; cd {os.getcwd()} && git status --short | wc -l"
        self.assertNotEqual("mutating", _kind(command))

    def test_the_label_helper_chained_with_a_write_is_still_a_write(self) -> None:
        self.assertEqual("mutating", _kind(f"{self.LABEL} >/dev/null 2>&1; rm -rf build"))


if __name__ == "__main__":
    unittest.main()
