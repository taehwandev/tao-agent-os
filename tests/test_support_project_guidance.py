import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from support.project_guidance import refresh_project_guidance
from support.setup_config_files import SetupConfigError

OLD = '''For a Codex leaf, use `dispatch --execute`
only when the selected model, reasoning effort, sandbox, or required isolation
differs from the parent. When the selected profile and sandbox match and
isolation is unnecessary, stay in the current process or use a native worker
instead of launching a fresh Codex process.'''


class ProjectGuidanceTests(unittest.TestCase):
    def test_refresh_is_scoped_backed_up_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / 'AGENTS.md'
            original = 'user before\n<!-- BEGIN MANAGED TAO AGENT OS ROUTING -->\n' + OLD + '\n<!-- END MANAGED TAO AGENT OS ROUTING -->\nuser after\n' + OLD
            target.write_text(original)
            self.assertEqual('missing', refresh_project_guidance(project, ROOT, dry_run=True)['status'])
            self.assertEqual(original, target.read_text())
            self.assertEqual('installed', refresh_project_guidance(project, ROOT, dry_run=False)['status'])
            updated = target.read_text()
            self.assertIn('only when isolation is explicitly required', updated)
            self.assertTrue(updated.endswith('user after\n' + OLD))
            self.assertEqual(original, target.with_name('AGENTS.md.tao-backup').read_text())
            self.assertEqual('ok', refresh_project_guidance(project, ROOT, dry_run=False)['status'])
            self.assertEqual(updated, target.read_text())
            self.assertEqual(original, target.with_name('AGENTS.md.tao-backup').read_text())

    def test_unmanaged_or_unknown_content_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / 'AGENTS.md'
            for original in ('user instructions', '<!-- BEGIN MANAGED TAO AGENT OS ROUTING -->custom<!-- END MANAGED TAO AGENT OS ROUTING -->'):
                target.write_text(original)
                with self.assertRaises(SetupConfigError):
                    refresh_project_guidance(project, ROOT, dry_run=False)
                self.assertEqual(original, target.read_text())
