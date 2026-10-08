from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.claude_agent_setup import (
    AGENT_NAMES,
    FRONTMATTER_FENCE,
    MANAGED_MARKER,
    SOURCE_SUFFIX,
    install_claude_agents,
)

TEMPLATES = ROOT / "templates" / "claude-agents"
MANAGED_HEADER = f"{FRONTMATTER_FENCE}\n{MANAGED_MARKER}\n"
READ_ONLY_TOOLS = "Edit, Write, NotebookEdit"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse the flat `key: value` frontmatter the templates use, without yaml."""

    lines = text.splitlines()
    if not lines or lines[0] != FRONTMATTER_FENCE:
        raise ValueError("missing opening frontmatter fence")
    end = lines.index(FRONTMATTER_FENCE, 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator or key != key.strip() or key in fields:
            raise ValueError(f"unsupported frontmatter line: {line!r}")
        fields[key] = value.strip()
    return fields, "\n".join(lines[end + 1:])


class ClaudeAgentSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.agents_dir = self.base / ".claude" / "agents"

    def install(self, *, root: Path = ROOT, dry_run: bool = False) -> list[dict]:
        return install_claude_agents(root, self.agents_dir, dry_run)

    def statuses(self, rows: list[dict]) -> dict[str, str]:
        return {row["hook"]: row["status"] for row in rows}

    def write_role(self, name: str, content: bytes) -> Path:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        target = self.agents_dir / f"{name}.md"
        target.write_bytes(content)
        return target

    def test_install_is_idempotent_and_returns_setup_rows(self) -> None:
        first = self.install()
        original_times = {
            path.name: path.stat().st_mtime_ns for path in self.agents_dir.iterdir()
        }
        second = self.install()
        self.assertEqual(["installed"] * 3, [row["status"] for row in first])
        self.assertEqual(["ok"] * 3, [row["status"] for row in second])
        self.assertEqual(original_times, {
            path.name: path.stat().st_mtime_ns for path in self.agents_dir.iterdir()
        })
        for name, row in zip(AGENT_NAMES, first):
            self.assertEqual({
                "tool": "claude", "hook": f"agents.{name}", "status": "installed",
                "path": str(self.agents_dir / f"{name}.md"),
            }, row)
            self.assertEqual(
                (TEMPLATES / f"{name}{SOURCE_SUFFIX}").read_bytes(), Path(row["path"]).read_bytes(),
            )

    def test_missing_dry_run_does_not_create_directory(self) -> None:
        rows = self.install(dry_run=True)
        self.assertEqual(["missing"] * 3, [row["status"] for row in rows])
        self.assertFalse(self.agents_dir.parent.exists())

    def test_stale_managed_role_updates_and_dry_run_preserves_it(self) -> None:
        stale = (MANAGED_HEADER + "name: tao_worker\n---\n").encode()
        target = self.write_role("tao_worker", stale)
        rows = self.install(dry_run=True)
        self.assertEqual("would_update", self.statuses(rows)["agents.tao_worker"])
        self.assertEqual(stale, target.read_bytes())
        self.assertEqual([target], list(self.agents_dir.iterdir()))
        self.assertEqual("installed", self.statuses(self.install())["agents.tao_worker"])
        self.assertEqual((TEMPLATES / f"tao_worker{SOURCE_SUFFIX}").read_bytes(), target.read_bytes())

    def test_same_name_user_role_and_unrelated_role_are_preserved(self) -> None:
        custom = b"---\nname: tao_worker\ndescription: Mine\n---\nMy instructions\n"
        target = self.write_role("tao_worker", custom)
        unrelated = self.write_role("my_reviewer", b"---\nname: my_reviewer\n---\n")
        for dry_run in (True, False):
            rows = self.install(dry_run=dry_run)
            self.assertEqual("conflict", self.statuses(rows)["agents.tao_worker"])
            self.assertEqual(custom, target.read_bytes())
            self.assertEqual(b"---\nname: my_reviewer\n---\n", unrelated.read_bytes())

    def test_marker_grants_ownership_only_as_second_line_after_fence(self) -> None:
        for original in (
            (MANAGED_MARKER + "\n---\nname: tao_worker\n---\n").encode(),
            ("---\nname: tao_worker\n" + MANAGED_MARKER + "\n---\n").encode(),
            ("# My role\n" + MANAGED_MARKER + "\n").encode(),
            (MANAGED_MARKER + "\n").encode(),
            b"",
        ):
            with self.subTest(original=original):
                target = self.write_role("tao_worker", original)
                self.assertEqual(
                    "conflict", self.statuses(self.install())["agents.tao_worker"],
                )
                self.assertEqual(original, target.read_bytes())

    def test_final_directory_symlink_is_preserved_without_following_it(self) -> None:
        external = self.base / "external"
        external.mkdir()
        self.agents_dir.parent.mkdir()
        self.agents_dir.symlink_to(external, target_is_directory=True)
        for dry_run in (True, False):
            self.assertEqual(["conflict"] * 3, [
                row["status"] for row in self.install(dry_run=dry_run)
            ])
            self.assertEqual([], list(external.iterdir()))
            self.assertTrue(self.agents_dir.is_symlink())

    def test_broken_final_directory_symlink_is_preserved(self) -> None:
        external = self.base / "missing-external"
        self.agents_dir.parent.mkdir()
        self.agents_dir.symlink_to(external, target_is_directory=True)
        self.assertEqual(["conflict"] * 3, [row["status"] for row in self.install()])
        self.assertTrue(self.agents_dir.is_symlink())
        self.assertFalse(external.exists())

    def test_role_symlink_is_preserved_even_when_target_is_managed(self) -> None:
        external = self.base / "external-role.md"
        original = (MANAGED_HEADER + "name: old\n---\n").encode()
        external.write_bytes(original)
        self.agents_dir.mkdir(parents=True)
        target = self.agents_dir / "tao_worker.md"
        target.symlink_to(external)
        for dry_run in (True, False):
            self.assertEqual("conflict", self.statuses(
                self.install(dry_run=dry_run)
            )["agents.tao_worker"])
            self.assertTrue(target.is_symlink())
            self.assertEqual(original, external.read_bytes())

    def test_broken_role_symlink_is_preserved(self) -> None:
        external = self.base / "missing-role.md"
        self.agents_dir.mkdir(parents=True)
        target = self.agents_dir / "tao_worker.md"
        target.symlink_to(external)
        self.assertEqual("conflict", self.statuses(self.install())["agents.tao_worker"])
        self.assertTrue(target.is_symlink())
        self.assertFalse(external.exists())

    def test_directory_at_role_path_and_file_at_agents_path_are_conflicts(self) -> None:
        self.agents_dir.mkdir(parents=True)
        target = self.agents_dir / "tao_worker.md"
        target.mkdir()
        self.assertEqual("conflict", self.statuses(self.install())["agents.tao_worker"])
        self.assertTrue(target.is_dir())
        self.agents_dir = self.base / "agents-file"
        self.agents_dir.write_bytes(b"preserve")
        self.assertEqual(["conflict"] * 3, [row["status"] for row in self.install()])
        self.assertEqual(b"preserve", self.agents_dir.read_bytes())

    def test_missing_source_fails_before_any_destination_writes(self) -> None:
        root = self.base / "source-root"
        source_dir = root / "templates" / "claude-agents"
        shutil.copytree(TEMPLATES, source_dir)
        (source_dir / f"{AGENT_NAMES[-1]}{SOURCE_SUFFIX}").unlink()
        for dry_run in (True, False):
            with self.assertRaises(FileNotFoundError):
                self.install(root=root, dry_run=dry_run)
            self.assertFalse(self.agents_dir.exists())

    def test_invalid_source_marker_fails_before_any_destination_writes(self) -> None:
        root = self.base / "source-root"
        source_dir = root / "templates" / "claude-agents"
        shutil.copytree(TEMPLATES, source_dir)
        (source_dir / f"{AGENT_NAMES[-1]}{SOURCE_SUFFIX}").write_bytes(
            (MANAGED_MARKER + "\n---\nname: tao_reviewer\n---\n").encode()
        )
        with self.assertRaisesRegex(ValueError, "ownership marker"):
            self.install(root=root)
        self.assertFalse(self.agents_dir.exists())

    def test_template_sources_are_not_markdown_documents(self) -> None:
        # A .md source would be validated as a Tao document card.
        self.assertEqual(
            sorted(f"{name}{SOURCE_SUFFIX}" for name in AGENT_NAMES),
            sorted(path.name for path in TEMPLATES.iterdir()),
        )

    def test_templates_have_subagent_schema_and_inherit_model(self) -> None:
        for name in AGENT_NAMES:
            with self.subTest(name=name):
                text = (TEMPLATES / f"{name}{SOURCE_SUFFIX}").read_text(encoding="utf-8")
                self.assertTrue(text.startswith(MANAGED_HEADER))
                fields, body = parse_frontmatter(text)
                read_only = name != "tao_worker"
                self.assertEqual(
                    {"name", "description", "model"}
                    | ({"disallowedTools"} if read_only else set()),
                    set(fields),
                )
                self.assertEqual(name, fields["name"])
                self.assertEqual("inherit", fields["model"])
                self.assertIn("parent", fields["description"])
                self.assertNotIn(": ", fields["description"])
                if read_only:
                    self.assertEqual(READ_ONLY_TOOLS, fields["disallowedTools"])
                    self.assertIn("Bash only for read-only commands", body)
                self.assertTrue(body.strip())
                self.assertNotIn(str(ROOT), text)
                self.assertNotIn("<TAO_LAUNCHER>", text)
                self.assertNotIn("Codex", text)


class ClaudeAgentIntegrationTests(unittest.TestCase):
    def configure(self, home: Path, dry_run: bool, root: Path = ROOT) -> list[dict]:
        from support.claude_setup import configure_claude

        with patch("support.claude_setup.Path.home", return_value=home):
            return configure_claude(
                dry_run, root=root, scripts_dir=root / "scripts",
                launcher_path=home / "bin" / "tao-hook", spill_available=False,
            )

    def test_runtime_setup_installs_roles_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = self.configure(home, False)
            second = self.configure(home, False)
            self.assertEqual(
                [f"agents.{name}" for name in AGENT_NAMES],
                [row["hook"] for row in first[:3]],
            )
            for name in AGENT_NAMES:
                self.assertEqual(
                    (TEMPLATES / f"{name}{SOURCE_SUFFIX}").read_text(),
                    (home / ".claude" / "agents" / f"{name}.md").read_text(),
                )
            self.assertEqual(["installed"] * 3, [row["status"] for row in first[:3]])
            self.assertEqual(["ok"] * 3, [row["status"] for row in second[:3]])

    def test_runtime_setup_dry_run_reports_roles_without_creating_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            roles = [row for row in self.configure(home, True)
                     if row["hook"].startswith("agents.")]
            self.assertEqual(["missing"] * 3, [row["status"] for row in roles])
            self.assertFalse((home / ".claude" / "agents").exists())

    def test_runtime_setup_missing_templates_stops_before_config_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            with self.assertRaises(FileNotFoundError):
                self.configure(home, False, root=Path(directory) / "missing-root")
            self.assertFalse(home.exists())

    def test_check_rejects_conflicting_and_stale_roles(self) -> None:
        from support.setup_agent_hooks_impl import fail_if_setup_incomplete

        for content, checks in (
            ("---\nname: tao_worker\n---\nuser-owned\n", (True, False)),
            (MANAGED_HEADER + "name: tao_worker\n---\n", (True,)),
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                self.configure(home, False)
                target = home / ".claude" / "agents" / "tao_worker.md"
                target.write_text(content, encoding="utf-8")
                results = self.configure(home, True)
                self.assertFalse(any(row["status"] == "missing" for row in results))
                for check in checks:
                    with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as exit_result:
                        fail_if_setup_incomplete(SimpleNamespace(check=check), results)
                    self.assertEqual(1, exit_result.exception.code)
                self.assertEqual(content, target.read_text())


if __name__ == "__main__":
    unittest.main()
