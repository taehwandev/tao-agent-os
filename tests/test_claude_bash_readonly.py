from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_bash_readonly as bash_readonly
import claude_worktree_gate as worktree_gate


class CompoundShellCommandTests(unittest.TestCase):
    """A compound command is judged by its parts, not by its punctuation.

    Treating every pipeline as mutating blocked plain inspection inside a
    protected checkout, so diagnosing the gate meant rewriting each command as a
    single call. It also ignored a `cd <worktree> &&` prefix once anything
    followed it, which left a session working in a linked worktree judged
    against the checkout it was launched from.
    """

    @staticmethod
    def _kind(command: str, cwd: Path | None = None) -> str:
        payload = {"tool_input": {"command": command}}
        base = cwd or Path("/tmp")
        _, tokens, simple = worktree_gate.bash_invocation(payload, base)
        return worktree_gate.bash_command_kind(tokens, simple)

    def test_read_only_pipeline_is_read_only(self) -> None:
        self.assertEqual(self._kind("grep -rn needle . | head -20"), "read_only")
        self.assertEqual(self._kind("ls -la | wc -l"), "read_only")
        self.assertEqual(self._kind("cat notes.txt | grep todo | tail -3"), "read_only")

    def test_one_mutating_part_makes_the_whole_command_mutating(self) -> None:
        self.assertEqual(self._kind("ls | rm -rf build"), "mutating")
        self.assertEqual(self._kind("grep -c x file && npm install"), "mutating")

    def test_redirection_to_a_file_is_never_read_only(self) -> None:
        self.assertEqual(self._kind("grep -rn needle . > findings.txt"), "mutating")
        self.assertEqual(self._kind("echo hi >> log.txt"), "mutating")

    def test_discarded_and_input_redirections_do_not_write(self) -> None:
        self.assertEqual(self._kind("grep -rn needle . 2>/dev/null"), "read_only")
        self.assertEqual(self._kind("ls -la 2>/dev/null | wc -l"), "read_only")
        self.assertEqual(self._kind("grep todo < notes.txt"), "read_only")

    def test_a_dangling_redirection_stays_mutating(self) -> None:
        self.assertEqual(self._kind("grep -rn needle . >"), "mutating")

    def test_an_operator_outside_the_modelled_set_is_not_a_read(self) -> None:
        """The lexer clusters metacharacters, so an unlisted operator is a word.

        `>|`, `&>`, `&>>`, `<>` and `>&` all write and all arrived as ordinary
        tokens, which both the simple path and the segment splitter read as
        arguments. Recognising the shape rather than the spelling is what keeps
        the enumeration from having to be complete.
        """

        self.assertEqual(self._kind("echo hi >| out.txt"), "mutating")
        self.assertEqual(self._kind("echo hi &> out.txt"), "mutating")
        self.assertEqual(self._kind("echo hi &>> out.txt"), "mutating")
        self.assertEqual(self._kind("echo hi <> out.txt"), "mutating")

    def test_descriptor_duplication_reads_while_a_filename_writes(self) -> None:
        """`2>&1` opens nothing; the same operator with a filename truncates it.

        Refusing `>&` on shape alone was correct about the operator and wrong
        about the operand, and it blocked `cmd 2>&1 | grep`, which is how a
        command's stderr gets read at all.
        """

        self.assertEqual(self._kind("echo hi 2>&1"), "read_only")
        self.assertEqual(self._kind("grep x notes.txt 2>&1 | head -3"), "read_only")
        self.assertEqual(self._kind("ls 1>&2"), "read_only")
        self.assertEqual(self._kind("cat notes.txt 2>&-"), "read_only")
        self.assertEqual(self._kind("ls >& out.txt"), "mutating")
        self.assertEqual(self._kind("ls 2>& out.txt"), "mutating")
        self.assertEqual(self._kind("ls >&"), "mutating")

    def test_substitution_runs_a_command_the_tokens_do_not_show(self) -> None:
        """`<(...)` executes a program that has no token of its own."""

        self.assertEqual(self._kind("cat <(rm -rf build)"), "mutating")
        self.assertEqual(self._kind("diff <(ls) <(ls)"), "mutating")
        self.assertEqual(self._kind("cat =(ls)"), "mutating")

    def test_an_abbreviated_unsafe_git_option_is_not_a_read(self) -> None:
        """Git accepts any unambiguous prefix, so exact matching missed them."""

        self.assertEqual(self._kind("git diff --ext-dif"), "mutating")
        self.assertEqual(self._kind("git log --textcon"), "mutating")
        self.assertEqual(self._kind("git log --outp=x"), "mutating")

    def test_a_transfer_program_option_is_not_bootstrap(self) -> None:
        """`fetch` is allowed as bootstrap, and these run a named binary."""

        self.assertEqual(self._kind("git fetch --upload-pack=/bin/sh"), "mutating")
        self.assertEqual(self._kind("git fetch --receive-pack=/bin/sh"), "mutating")
        self.assertEqual(self._kind("git fetch --exec=/bin/sh"), "mutating")
        self.assertEqual(self._kind("git fetch origin"), "bootstrap")

    def test_git_config_injection_is_not_a_read(self) -> None:
        """`-c` can hand a read-shaped Git command a program to run.

        `diff.external`, `core.pager`, `*.textconv` and the `filter.*` hooks are
        all reachable this way, so the option was skipped as though only its
        value mattered and `git -c diff.external=... diff` classified as
        read-only while Git went on to execute the named program.
        """

        self.assertEqual(self._kind("git -c diff.external=/bin/sh diff"), "mutating")
        self.assertEqual(self._kind("git -c core.pager=/bin/sh log"), "mutating")
        self.assertEqual(
            self._kind("git --config-env=diff.external=EVIL diff"), "mutating"
        )
        self.assertEqual(self._kind("git --exec-path=/tmp/evil log"), "mutating")

    def test_git_options_that_only_choose_a_repository_still_read(self) -> None:
        self.assertEqual(self._kind("git -C /tmp/checkout status"), "read_only")
        self.assertEqual(self._kind("git --git-dir=/tmp/x/.git log"), "read_only")
        self.assertEqual(self._kind("git --no-pager diff --stat"), "read_only")

    def test_an_executor_environment_assignment_is_not_a_read(self) -> None:
        """An assignment prefix can supply the program the command runs.

        Stripping every `NAME=value` token by shape alone judged the command
        that followed and never the variable in front of it, so a library
        injected into `cat` or a Git config synthesised from the environment
        arrived as a read.
        """

        self.assertEqual(
            self._kind("LD_PRELOAD=/tmp/evil.so cat notes.txt"), "mutating"
        )
        self.assertEqual(
            self._kind("DYLD_INSERT_LIBRARIES=/tmp/evil.dylib ls"), "mutating"
        )
        self.assertEqual(self._kind("BASH_ENV=/tmp/evil.sh grep x notes.txt"), "mutating")
        self.assertEqual(self._kind("GIT_EXTERNAL_DIFF=/bin/sh git diff"), "mutating")
        self.assertEqual(self._kind("GIT_PAGER=/bin/sh git log"), "mutating")
        self.assertEqual(
            self._kind(
                "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.external "
                "GIT_CONFIG_VALUE_0=/bin/sh git diff"
            ),
            "mutating",
        )

    def test_print_only_sed_reading_stdin_stays_read_only(self) -> None:
        """`... | sed -n 2p` writes nothing; the missing file operand is stdin."""

        self.assertEqual(self._kind("grep -rn needle notes.txt | sed -n 2p"), "read_only")
        self.assertEqual(self._kind("sed -i s/a/b/ notes.txt"), "mutating")

    def test_bare_cd_only_moves_the_shell_and_stays_read_only(self) -> None:
        """A lone `cd` cannot write; stranding a parked shell was the only effect."""

        self.assertEqual(self._kind("cd /tmp/anywhere"), "read_only")
        self.assertEqual(self._kind("cd .."), "read_only")

    def test_presentation_only_environment_assignments_still_read(self) -> None:
        self.assertEqual(self._kind("LC_ALL=C git log --oneline"), "read_only")
        self.assertEqual(self._kind("LANG=C grep needle notes.txt"), "read_only")
        self.assertEqual(self._kind("TZ=UTC date"), "read_only")

    def test_runtime_hook_environment_assignments_keep_the_control_kind(self) -> None:
        """The runtime's own documented env prefixes must not void its hooks.

        `CLAUDE_CODE_SESSION_ID` and `TAO_HOOK_SOFT_FAIL` are read only by this
        runtime's tooling and never select what executes, but the executor-variable
        fail-close treated them like `LD_PRELOAD`, so the gate denied the exact
        start command its own denial message asks the caller to run.
        """

        launcher = str(worktree_gate.stable_launcher_path())
        self.assertEqual(
            self._kind(
                f"CLAUDE_CODE_SESSION_ID=abc123 {launcher} start "
                "--project /tmp/x --request hi"
            ),
            "workflow_start",
        )
        self.assertEqual(
            self._kind(f"TAO_HOOK_SOFT_FAIL=1 {launcher} finish"), "bootstrap"
        )
        self.assertEqual(
            self._kind("CLAUDE_CODE_SESSION_ID=abc123 grep needle notes.txt"),
            "read_only",
        )
        self.assertEqual(
            self._kind(f"LD_PRELOAD=/tmp/evil.so {launcher} start"), "mutating"
        )

    def test_fingerprint_hook_is_runtime_control(self) -> None:
        """The envelope bootstrap helper must be callable before any start."""

        launcher = str(worktree_gate.stable_launcher_path())
        self.assertEqual(
            self._kind(f'{launcher} fingerprint --request "do the thing"'),
            "bootstrap",
        )

    def test_chained_runtime_control_hook_does_not_bootstrap(self) -> None:
        launcher = str(worktree_gate.stable_launcher_path())
        self.assertEqual(self._kind(f"{launcher} finish && rm -rf build"), "mutating")

    def test_chaining_read_only_parts_keeps_the_bootstrap_allowance(self) -> None:
        """The deny message asks for a worktree; chaining must not void it.

        `git fetch && git worktree add` is the documented way out of a
        main-checkout denial. Treating the chain itself as the smuggling risk
        made the gate refuse its own instructions, while the case it guards
        against -- a control hook next to a write -- is still caught by the
        write's own `mutating` verdict.
        """
        self.assertEqual(
            self._kind("git fetch -p origin develop && git worktree add ../task develop"),
            "bootstrap",
        )
        launcher = str(worktree_gate.stable_launcher_path())
        self.assertEqual(self._kind(f"{launcher} finish | tail -20"), "bootstrap")

    def test_workflow_start_is_the_strictest_allowance_in_a_chain(self) -> None:
        launcher = str(worktree_gate.stable_launcher_path())
        self.assertEqual(self._kind(f"{launcher} start --project . | tail -5"), "workflow_start")
        self.assertEqual(
            self._kind(f"git fetch origin && {launcher} start --project ."),
            "workflow_start",
        )

    def test_cd_prefix_still_names_the_directory_for_a_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            payload = {"tool_input": {"command": f"cd {target} && grep -rn x . | head -3"}}
            effective_cwd, tokens, simple = worktree_gate.bash_invocation(payload, Path("/"))

            self.assertEqual(effective_cwd, target)
            self.assertFalse(simple)
            self.assertEqual(worktree_gate.bash_command_kind(tokens, simple), "read_only")

    def test_cd_prefix_with_a_single_command_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            payload = {"tool_input": {"command": f"cd {target} && ls -la"}}
            effective_cwd, tokens, simple = worktree_gate.bash_invocation(payload, Path("/"))

            self.assertEqual(effective_cwd, target)
            self.assertTrue(simple)
            self.assertEqual(worktree_gate.bash_command_kind(tokens, simple), "read_only")

    def test_unparseable_syntax_stays_mutating(self) -> None:
        self.assertEqual(self._kind("python3 - <<'PY'\nprint(1)\nPY"), "mutating")
        self.assertEqual(self._kind("echo $(rm -rf build)"), "mutating")


class ReadOnlyScriptDeclarationTests(unittest.TestCase):
    """An interpreter is judged by the script it runs, never by its name.

    Every interpreter invocation used to fall through to mutating, so a
    protected checkout could not run a read-only query tool at all. Naming
    `python3` itself read-only would have handed inline code the same
    allowance, so the entry is a script path and the script has to be the
    interpreter's first argument.
    """

    DECLARATIONS_ENV = "TAO_CLAUDE_READ_ONLY_PYTHON_SCRIPTS"

    @staticmethod
    def _kind(command: str, cwd: Path = Path("/tmp")) -> str:
        payload = {"tool_input": {"command": command}}
        _, tokens, simple = bash_readonly.bash_invocation(payload, cwd)
        return bash_readonly.bash_command_kind(tokens, simple)

    def setUp(self) -> None:
        self._state = tempfile.TemporaryDirectory()
        self.addCleanup(self._state.cleanup)
        state_dir = Path(self._state.name).resolve()
        self.script = state_dir / "query.py"
        self.script.write_text("print('ok')\n", encoding="utf-8")
        self.interpreter = Path(sys.executable).resolve()
        self.digest = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.declaration = {
            "schema_version": 1,
            "scripts": [{"path": str(self.script), "sha256": self.digest}],
        }
        patcher = patch.dict(
            os.environ,
            {self.DECLARATIONS_ENV: json.dumps(self.declaration)},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _command(
        self,
        script: Path | str | None = None,
        interpreter: Path | str | None = None,
    ) -> str:
        selected_script = self.script if script is None else script
        selected_interpreter = self.interpreter if interpreter is None else interpreter
        return f"{shlex.quote(str(selected_interpreter))} {shlex.quote(str(selected_script))}"

    def _set_declaration(self, declaration: object) -> None:
        os.environ[self.DECLARATIONS_ENV] = json.dumps(declaration)

    def test_a_digest_bound_script_is_read_only(self) -> None:
        self.assertEqual(self._kind(self._command()), "read_only")
        self.assertEqual(
            self._kind(f"{self._command()} GET /rest/api/3/issue/X-1"),
            "read_only",
        )

    def test_an_undeclared_script_stays_mutating(self) -> None:
        other = self.script.with_name("other.py")
        other.write_text("print('no')\n", encoding="utf-8")
        self.assertEqual(self._kind(self._command(other)), "mutating")

    def test_interpreter_flags_never_reach_the_allowance(self) -> None:
        interpreter = shlex.quote(str(self.interpreter))
        script = shlex.quote(str(self.script))
        self.assertEqual(self._kind(f'{interpreter} -c "print(1)"'), "mutating")
        self.assertEqual(self._kind(f"{interpreter} -m pdb {script}"), "mutating")
        self.assertEqual(self._kind(f"{interpreter} -i"), "mutating")

    def test_a_redirection_still_writes(self) -> None:
        self.assertEqual(self._kind(f"{self._command()} > out.json"), "mutating")

    def test_a_writable_state_file_no_longer_authorizes_a_script(self) -> None:
        state_dir = Path(self._state.name)
        (state_dir / "read-only-scripts.json").write_text(
            json.dumps({"scripts": [str(self.script)]}), encoding="utf-8"
        )
        with patch.dict(os.environ, {"TAO_STATE_HOME": str(state_dir)}):
            os.environ.pop(self.DECLARATIONS_ENV, None)
            self.assertEqual(self._kind(self._command()), "mutating")

    def test_malformed_json_allows_nothing(self) -> None:
        os.environ[self.DECLARATIONS_ENV] = "{"
        self.assertEqual(self._kind(self._command()), "mutating")

    def test_a_nul_path_declaration_allows_nothing(self) -> None:
        self._set_declaration(
            {
                "schema_version": 1,
                "scripts": [{"path": "/tmp/query.py\u0000", "sha256": self.digest}],
            }
        )
        self.assertEqual(self._kind(self._command()), "mutating")

    def test_a_relative_path_declaration_allows_nothing(self) -> None:
        self._set_declaration(
            {
                "schema_version": 1,
                "scripts": [{"path": "query.py", "sha256": self.digest}],
            }
        )
        self.assertEqual(self._kind(self._command()), "mutating")

    def test_a_missing_script_declaration_allows_nothing(self) -> None:
        missing = self.script.with_name("missing.py")
        self._set_declaration(
            {
                "schema_version": 1,
                "scripts": [{"path": str(missing), "sha256": self.digest}],
            }
        )
        self.assertEqual(self._kind(self._command(missing)), "mutating")

    def test_a_digest_mismatch_allows_nothing(self) -> None:
        self._set_declaration(
            {
                "schema_version": 1,
                "scripts": [{"path": str(self.script), "sha256": "0" * 64}],
            }
        )
        self.assertEqual(self._kind(self._command()), "mutating")

    def test_editing_a_declared_script_revokes_the_allowance(self) -> None:
        self.script.write_text("print('changed')\n", encoding="utf-8")
        self.assertEqual(self._kind(self._command()), "mutating")

    def test_a_symlink_declaration_allows_nothing(self) -> None:
        link = self.script.with_name("query-link.py")
        link.symlink_to(self.script)
        self._set_declaration(
            {
                "schema_version": 1,
                "scripts": [{"path": str(link), "sha256": self.digest}],
            }
        )
        self.assertEqual(self._kind(self._command(link)), "mutating")

    def test_a_spoofed_interpreter_allows_nothing(self) -> None:
        spoofed = self.script.with_name("python3")
        spoofed.write_text("#!/bin/sh\n", encoding="utf-8")
        spoofed.chmod(0o755)
        self.assertEqual(self._kind(self._command(interpreter=spoofed)), "mutating")

    def test_a_relative_script_after_cd_allows_nothing(self) -> None:
        command = (
            f"cd {shlex.quote(str(self.script.parent))} && "
            f"{shlex.quote(str(self.interpreter))} {shlex.quote(self.script.name)}"
        )
        self.assertEqual(self._kind(command), "mutating")


class OptionJudgedInspectionCommandTests(unittest.TestCase):
    """A command with one narrow write path is judged by its options.

    `find` and `sort` were excluded outright because each can be made to write,
    which denied every use of them and left no way to list or order a directory
    inside a protected checkout. `sed` was admitted only as `-n <range>p`, so a
    pipeline could read output but not reshape it.
    """

    @staticmethod
    def _kind(command: str) -> str:
        payload = {"tool_input": {"command": command}}
        _, tokens, simple = worktree_gate.bash_invocation(payload, Path("/tmp"))
        return worktree_gate.bash_command_kind(tokens, simple)

    def test_find_without_an_action_only_reads(self) -> None:
        self.assertEqual(self._kind("find . -type f"), "read_only")
        self.assertEqual(self._kind("find src -name '*.kt' | sort"), "read_only")
        self.assertEqual(self._kind("find . -maxdepth 2 -type d -newer x"), "read_only")

    def test_every_find_action_that_runs_or_writes_is_mutating(self) -> None:
        self.assertEqual(self._kind("find . -delete"), "mutating")
        self.assertEqual(self._kind("find . -name '*.tmp' -delete"), "mutating")
        self.assertEqual(self._kind("find . -exec rm {} \\;"), "mutating")
        self.assertEqual(self._kind("find . -execdir rm {} \\;"), "mutating")
        self.assertEqual(self._kind("find . -ok rm {} \\;"), "mutating")
        self.assertEqual(self._kind("find . -okdir rm {} \\;"), "mutating")
        self.assertEqual(self._kind("find . -fprint out.txt"), "mutating")
        self.assertEqual(self._kind("find . -fprintf out.txt '%p'"), "mutating")
        self.assertEqual(self._kind("find . -fls out.txt"), "mutating")

    def test_sort_output_and_temporary_file_options_are_mutating(self) -> None:
        self.assertEqual(self._kind("sort notes.txt"), "read_only")
        self.assertEqual(self._kind("sort -u -r notes.txt | head -5"), "read_only")
        self.assertEqual(self._kind("sort -o sorted.txt notes.txt"), "mutating")
        self.assertEqual(self._kind("sort --output=sorted.txt notes.txt"), "mutating")
        self.assertEqual(self._kind("sort -uo sorted.txt notes.txt"), "mutating")
        self.assertEqual(self._kind("sort -T . notes.txt"), "mutating")
        self.assertEqual(
            self._kind("sort --temporary-directory=. notes.txt"), "mutating"
        )

    def test_sort_cannot_run_a_compression_program(self) -> None:
        self.assertEqual(
            self._kind("sort --compress-program=/tmp/writer notes.txt"), "mutating"
        )

    def test_an_abbreviated_sort_output_option_is_still_a_write(self) -> None:
        """Long options abbreviate, so an exact-string check reads one as a word."""

        self.assertEqual(self._kind("sort --outp=sorted.txt notes.txt"), "mutating")
        self.assertEqual(self._kind("sort --out sorted.txt notes.txt"), "mutating")
        self.assertEqual(self._kind("sort --temp=. notes.txt"), "mutating")
        self.assertEqual(self._kind("sort --comp=/tmp/writer notes.txt"), "mutating")

    def test_a_printing_or_substituting_sed_writes_nothing(self) -> None:
        self.assertEqual(self._kind("sed -n '1,5p' notes.txt"), "read_only")
        self.assertEqual(self._kind("ls | sed 's|.*/||'"), "read_only")
        self.assertEqual(self._kind("sed 's/a/b/g' notes.txt"), "read_only")
        self.assertEqual(self._kind("sed -n 's/a/b/p' notes.txt"), "read_only")
        self.assertEqual(self._kind("sed -e 's/a/b/' -e '1,2p' notes.txt"), "read_only")

    def test_a_sed_that_opens_a_file_or_a_shell_is_mutating(self) -> None:
        self.assertEqual(self._kind("sed -i 's/a/b/' notes.txt"), "mutating")
        self.assertEqual(self._kind("sed -i.bak 's/a/b/' notes.txt"), "mutating")
        self.assertEqual(self._kind("sed 's/a/b/w out.txt' notes.txt"), "mutating")
        self.assertEqual(self._kind("sed 'w out.txt' notes.txt"), "mutating")
        self.assertEqual(self._kind("sed 's/a/b/e' notes.txt"), "mutating")
        self.assertEqual(self._kind("sed"), "mutating")

    def test_a_sed_option_after_the_script_is_still_read(self) -> None:
        """GNU sed accepts options after its operands, so position decides nothing."""

        self.assertEqual(self._kind("sed 's/a/b/' -i notes.txt"), "mutating")

    def test_an_unreadable_sed_script_is_refused(self) -> None:
        """A delimiter holding the separator makes the script unparseable here."""

        self.assertEqual(self._kind("sed 's/a;b/c/' notes.txt"), "mutating")


class ShellKeywordSegmentTests(unittest.TestCase):
    """A loop or branch is judged by the commands in it, not by its keywords.

    Splitting on `;` left `for`, `do` and `done` sitting where a program name
    belongs, so every loop was mutating and the one shape that iterates over
    files could not be used to look at a protected checkout.
    """

    @staticmethod
    def _kind(command: str) -> str:
        payload = {"tool_input": {"command": command}}
        _, tokens, simple = worktree_gate.bash_invocation(payload, Path("/tmp"))
        return worktree_gate.bash_command_kind(tokens, simple)

    def test_a_loop_over_read_only_commands_is_read_only(self) -> None:
        self.assertEqual(
            self._kind('for f in a.kt b.kt; do head -3 "$f"; done'), "read_only"
        )
        self.assertEqual(
            self._kind('while true; do ls; done'), "read_only"
        )

    def test_a_write_inside_a_loop_body_still_decides(self) -> None:
        self.assertEqual(self._kind('for f in *; do rm "$f"; done'), "mutating")
        self.assertEqual(
            self._kind('for f in *; do cat "$f" > out.txt; done'), "mutating"
        )

    def test_a_branch_is_judged_by_both_of_its_arms(self) -> None:
        self.assertEqual(self._kind('if grep -q x f; then cat f; fi'), "read_only")
        self.assertEqual(self._kind('if ls; then rm -rf build; fi'), "mutating")

    def test_an_else_arm_is_not_skipped(self) -> None:
        """A keyword that opens a block is stripped, never treated as the whole part."""

        self.assertEqual(
            self._kind('if ls; then cat f; else rm -rf build; fi'), "mutating"
        )

    def test_a_terminator_carrying_more_words_is_not_understood(self) -> None:
        self.assertEqual(self._kind('ls; done rm -rf build'), "mutating")

class ReviewOnTheCurrentBranchTests(unittest.TestCase):
    """A review reads history, and reading history is not a mutation.

    Reviewing work on the branch it is already on is something a person asks
    for directly. `blame`, `describe`, `shortlog` and `whatchanged` were absent
    from the read set rather than excluded from it, so they failed closed and
    the reviewer could not answer the question a review is for.
    """

    @staticmethod
    def _kind(command: str) -> str:
        payload = {"tool_input": {"command": command}}
        _, tokens, simple = worktree_gate.bash_invocation(payload, Path("/tmp"))
        return worktree_gate.bash_command_kind(tokens, simple)

    def test_history_reading_subcommands_are_read_only(self) -> None:
        for command in (
            "git blame README.md",
            "git describe --tags",
            "git shortlog -sn",
            "git whatchanged -3",
            "git ls-tree HEAD",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", self._kind(command))

    def test_history_writing_subcommands_are_still_mutating(self) -> None:
        # The widening must not reach anything that changes history.
        for command in (
            "git commit -m x",
            "git rebase main",
            "git reset --hard",
            "git checkout -b x",
            "git blame --help; rm -rf .",
        ):
            with self.subTest(command=command):
                self.assertNotEqual("read_only", self._kind(command))



class InspectionIsNotMutationTests(unittest.TestCase):
    """Reading a repository should not need permission to change it.

    The read-only subcommand list covered the commands people type by hand and
    stopped there, so `git merge-base`, `git show-ref`, `git cat-file`,
    `git rev-list`, `git for-each-ref`, `git grep` and `git tag --list` -- none
    of which can write anything -- were classified as mutations. Inside a
    protected checkout that left an agent unable to read the repository it was
    asked about: tight in the one place tightness buys nothing, which is how a
    guard becomes the thing people switch off.

    The other half still has to hold. Several of these subcommands take a flag
    that writes a file or runs a program, and widening the list is exactly what
    brings those flags into reach.
    """

    def test_pure_inspection_is_read_only(self) -> None:
        from claude_bash_git import git_command_kind

        for command in (
            "git merge-base --is-ancestor a b",
            "git cat-file -p HEAD",
            "git rev-list --count HEAD",
            "git for-each-ref",
            "git show-ref",
            "git ls-remote origin",
            "git diff-tree HEAD",
            "git name-rev HEAD",
            "git cherry main",
            "git count-objects -v",
            "git verify-commit HEAD",
            "git grep needle",
            "git tag",
            "git tag --list",
            "git tag -l v1*",
            "git stash list",
            "git stash show",
            "git submodule status",
            "git symbolic-ref HEAD",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", git_command_kind(command.split()))

    def test_the_writing_forms_of_the_same_subcommands_are_not(self) -> None:
        from claude_bash_git import git_command_kind

        for command in (
            "git tag v1",
            "git tag -d v1",
            "git tag -a v1 -m x",
            "git tag -f v1 HEAD",
            "git stash",
            "git stash drop",
            "git stash pop",
            "git submodule update",
            "git symbolic-ref HEAD refs/heads/x",
            "git symbolic-ref -d HEAD",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", git_command_kind(command.split()))

    def test_a_pager_flag_still_counts_as_running_a_program(self) -> None:
        """`git grep -O<cmd>` opens matches in <cmd>.

        Both spellings arrive with the subcommands widened above, so both are
        named. The long form is caught by prefix, which covers abbreviations;
        the short form carries its command attached and needs its own check.
        """

        from claude_bash_git import git_command_kind

        for command in (
            "git grep --open-files-in-pager=vi needle",
            "git grep --open-files needle",
            "git grep -Oless needle",
            "git grep -O needle",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", git_command_kind(command.split()))


if __name__ == "__main__":
    unittest.main()
