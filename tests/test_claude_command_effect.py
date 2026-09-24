from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_bash_readonly import bash_invocation, bash_command_kind
from claude_command_effect import INTERPRETER_REASON, command_effect, github_publication, unknown_recovery


class CommandEffectTests(unittest.TestCase):
    def test_unknown_project_script_recovery_names_the_publication_declaration(self):
        """A publishing project script is fixed by declaring it, which the denial must say."""
        tokens = ['python3', 'tools/bitbucket_pr/create_pr.py', '--source', 'feature', '--dest', 'develop']
        effect, reason = command_effect(tokens, True, 'mutating')
        self.assertEqual(('unknown', INTERPRETER_REASON), (effect, reason))
        self.assertIn('publication_commands in .agents/shared/worktree-policy.json', unknown_recovery(reason))
        self.assertNotIn('publication_commands',
                         unknown_recovery('command or options have no verified effect contract'))

    def test_only_a_finished_session_is_told_to_continue_without_a_start(self):
        """An unknown effect with no finished run still needs its writable route."""
        for reason in (INTERPRETER_REASON, 'command or options have no verified effect contract'):
            with self.subTest(reason=reason):
                self.assertNotIn('without another workflow start', unknown_recovery(reason))
                self.assertIn('Enter its scoped writable route once', unknown_recovery(reason))
                self.assertIn('continue without another workflow start',
                              unknown_recovery(reason, after_finish=True))

    def test_publication_action_contract_does_not_depend_on_workflow_state(self):
        for command in (
            'gh release create v1 --notes-file /tmp/notes.md',
            'gh release upload v1 package.tgz',
            'gh api --method=POST repos/owner/repo/releases -f tag_name=v1',
            'gh api repos/owner/repo/actions/runs/42/pending_deployments -f state=approved',
        ):
            with self.subTest(command=command):
                self.assertEqual('mutating', self.effect(command)[0])

    def test_publication_contract_excludes_reads_and_unrelated_authority(self):
        import shlex
        for command in (
            'gh release view v1', 'gh release delete v1', 'gh pr merge 1',
            'gh api repos/owner/repo/releases',
            'gh api -X DELETE repos/owner/repo/releases',
            'gh api -X POST repos/owner/repo/hooks',
            'gh api -X POST graphql -f query=mutation',
            'gh api -X POST repos/owner/repo/releases --hostname other.test',
            'gh api -X POST repos/owner/repo/releases -X GET',
            'gh api -X POST repos/owner/repo/releases --input',
            'gh api -X POST repos/owner/repo/releases extra',
        ):
            with self.subTest(command=command):
                self.assertFalse(github_publication(shlex.split(command)))

    def test_release_notes_and_api_input_are_read_operands(self):
        from claude_bash_readonly import read_only_path_token_indices
        for tokens in (
            ['gh', 'release', 'create', 'v1', '--notes-file', '/tmp/notes.md'],
            ['gh', 'api', 'repos/owner/repo/releases', '--input', '/tmp/body.json'],
        ):
            self.assertIn(len(tokens) - 1, read_only_path_token_indices(tokens))
            chained = tokens + ['&&', 'touch', tokens[-1]]
            self.assertNotIn(len(chained) - 1, read_only_path_token_indices(chained))

    def test_branch_changes_keep_the_mutation_contract(self):
        for command in (
            "git switch -c owner/task", "git switch main",
            "git checkout -b owner/task", "git checkout -- file",
            "git branch owner/task", "git branch -d --force owner/task",
            "git branch -D main", "git branch -m old new",
            "git -C /tmp/project switch -c owner/task",
            "cd /tmp/project && git checkout -b owner/task",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", self.effect(command)[0])
        # Git refuses an unmerged `branch -d` itself: admitted ref cleanup.
        self.assertEqual("bootstrap", self.effect("git branch -d owner/task")[0])

    def test_branch_reads_and_unknown_git_commands_stay_distinct(self):
        for command in ("git branch", "git branch -vv", "git branch --list owner/task",
                        "git -C /tmp/project branch --merged main"):
            with self.subTest(command=command):
                self.assertEqual("read_only", self.effect(command)[0])
        for command in ("git custom-alias", "git --unknown-global switch main"):
            with self.subTest(command=command):
                self.assertEqual("unknown", self.effect(command)[0])

    def effect(self, command):
        _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
        return command_effect(tokens, simple, bash_command_kind(tokens, simple))

    def test_effects_are_distinct_without_changing_legacy_authority(self):
        for command, expected in (
            ("rg value file", "read_only"),
            ("curl -q https://example.test", "read_only"),
            ("touch file", "mutating"),
            ("cat file | tee destination", "mutating"),
            ("curl -q -X POST https://example.test", "mutating"),
            ("curl -q -o saved.json https://example.test", "mutating"),
            ("curl -q -H '-XPOST' https://example.test", "read_only"),
            ("cat file > destination", "mutating"),
            ("custom-tool inspect", "unknown"),
            ("python3 custom.py", "unknown"),
            ("curl https://example.test", "unknown"),
            ("curl -q --unknown https://example.test", "unknown"),
        ):
            with self.subTest(command=command):
                self.assertEqual(expected, self.effect(command)[0])

    def test_unknown_explanation_names_boundary_without_echoing_sensitive_arguments(self):
        effect, reason = self.effect("curl -H 'Authorization: Bearer PRIVATE' https://example.test/private")
        self.assertEqual("unknown", effect)
        self.assertIn("put -q first", reason)
        self.assertNotIn("PRIVATE", reason)
        self.assertNotIn("example.test", reason)

    def test_unparsed_or_mixed_command_never_becomes_a_verified_read(self):
        for command in ("cat file && custom-tool", "curl -q https://example.test | tee saved", "echo $(python3 unknown.py)"):
            self.assertNotEqual("read_only", self.effect(command)[0])
