from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.codex_agent_setup import AGENT_NAMES, MANAGED_MARKER, install_codex_agents


class CodexAgentSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.agents_dir = self.base / ".codex" / "agents"

    def install(self, *, root: Path = ROOT, dry_run: bool = False) -> list[dict]:
        return install_codex_agents(root, self.agents_dir, dry_run)

    def statuses(self, rows: list[dict]) -> dict[str, str]:
        return {row["hook"]: row["status"] for row in rows}

    def write_role(self, name: str, content: bytes) -> Path:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        target = self.agents_dir / f"{name}.toml"
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
                "tool": "codex", "hook": f"agents.{name}", "status": "installed",
                "path": str(self.agents_dir / f"{name}.toml"),
            }, row)
            self.assertEqual(
                (ROOT / "templates" / "codex-agents" / f"{name}.toml").read_bytes(),
                Path(row["path"]).read_bytes(),
            )

    def test_missing_dry_run_does_not_create_directory(self) -> None:
        rows = self.install(dry_run=True)
        self.assertEqual(["missing"] * 3, [row["status"] for row in rows])
        self.assertFalse(self.agents_dir.parent.exists())

    def test_stale_managed_role_updates_and_dry_run_preserves_it(self) -> None:
        stale = (MANAGED_MARKER + '\nname = "tao_worker"\n').encode()
        target = self.write_role("tao_worker", stale)
        rows = self.install(dry_run=True)
        self.assertEqual("would_update", self.statuses(rows)["agents.tao_worker"])
        self.assertEqual(stale, target.read_bytes())
        self.assertEqual([target], list(self.agents_dir.iterdir()))
        self.assertEqual("installed", self.statuses(self.install())["agents.tao_worker"])
        self.assertEqual(
            (ROOT / "templates" / "codex-agents" / target.name).read_bytes(),
            target.read_bytes(),
        )

    def test_same_name_user_role_and_unrelated_role_are_preserved(self) -> None:
        custom = b'name = "tao_worker"\ndeveloper_instructions = "My instructions"\n'
        target = self.write_role("tao_worker", custom)
        unrelated = self.write_role("my_reviewer", b'name = "my_reviewer"\n')
        for dry_run in (True, False):
            rows = self.install(dry_run=dry_run)
            self.assertEqual("conflict", self.statuses(rows)["agents.tao_worker"])
            self.assertEqual(custom, target.read_bytes())
            self.assertEqual(b'name = "my_reviewer"\n', unrelated.read_bytes())

    def test_unmanaged_marker_later_in_file_does_not_grant_ownership(self) -> None:
        original = ("# My role\n" + MANAGED_MARKER + "\n").encode()
        target = self.write_role("tao_worker", original)
        self.assertEqual("conflict", self.statuses(self.install())["agents.tao_worker"])
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
        external = self.base / "external-role.toml"
        original = (MANAGED_MARKER + "\n# old role\n").encode()
        external.write_bytes(original)
        self.agents_dir.mkdir(parents=True)
        target = self.agents_dir / "tao_worker.toml"
        target.symlink_to(external)
        for dry_run in (True, False):
            self.assertEqual("conflict", self.statuses(
                self.install(dry_run=dry_run)
            )["agents.tao_worker"])
            self.assertTrue(target.is_symlink())
            self.assertEqual(original, external.read_bytes())

    def test_broken_role_symlink_is_preserved(self) -> None:
        external = self.base / "missing-role.toml"
        self.agents_dir.mkdir(parents=True)
        target = self.agents_dir / "tao_worker.toml"
        target.symlink_to(external)
        self.assertEqual("conflict", self.statuses(self.install())["agents.tao_worker"])
        self.assertTrue(target.is_symlink())
        self.assertFalse(external.exists())

    def test_directory_at_role_path_and_file_at_agents_path_are_conflicts(self) -> None:
        self.agents_dir.mkdir(parents=True)
        target = self.agents_dir / "tao_worker.toml"
        target.mkdir()
        self.assertEqual("conflict", self.statuses(self.install())["agents.tao_worker"])
        self.assertTrue(target.is_dir())
        self.agents_dir = self.base / "agents-file"
        self.agents_dir.write_bytes(b"preserve")
        self.assertEqual(["conflict"] * 3, [row["status"] for row in self.install()])
        self.assertEqual(b"preserve", self.agents_dir.read_bytes())

    def test_missing_source_fails_before_any_destination_writes(self) -> None:
        root = self.base / "source-root"
        source_dir = root / "templates" / "codex-agents"
        shutil.copytree(ROOT / "templates" / "codex-agents", source_dir)
        (source_dir / f"{AGENT_NAMES[-1]}.toml").unlink()
        for dry_run in (True, False):
            with self.assertRaises(FileNotFoundError):
                self.install(root=root, dry_run=dry_run)
            self.assertFalse(self.agents_dir.exists())

    def test_invalid_source_marker_fails_before_any_destination_writes(self) -> None:
        root = self.base / "source-root"
        source_dir = root / "templates" / "codex-agents"
        shutil.copytree(ROOT / "templates" / "codex-agents", source_dir)
        (source_dir / f"{AGENT_NAMES[-1]}.toml").write_bytes(b'name = "unknown"\n')
        with self.assertRaisesRegex(ValueError, "ownership marker"):
            self.install(root=root)
        self.assertFalse(self.agents_dir.exists())

    @unittest.skipUnless(tomllib is not None, "stdlib TOML parsing requires Python 3.11")
    def test_templates_have_native_schema_and_inherit_model_and_worker_permissions(self) -> None:
        for name in AGENT_NAMES:
            with self.subTest(name=name):
                source = ROOT / "templates" / "codex-agents" / f"{name}.toml"
                text = source.read_text(encoding="utf-8")
                self.assertEqual(MANAGED_MARKER, text.splitlines()[0])
                role = tomllib.loads(text)
                self.assertEqual(name, role["name"])
                self.assertTrue(role["description"].strip())
                self.assertTrue(role["developer_instructions"].strip())
                self.assertEqual(
                    {"name", "description", "developer_instructions"}
                    | ({"sandbox_mode"} if name != "tao_worker" else set()),
                    set(role),
                )
                if name == "tao_worker":
                    self.assertNotIn("sandbox_mode", role)
                else:
                    self.assertEqual("read-only", role["sandbox_mode"])
                self.assertNotIn(str(ROOT), text)
                self.assertNotIn("<TAO_LAUNCHER>", text)


if __name__ == "__main__":
    unittest.main()
