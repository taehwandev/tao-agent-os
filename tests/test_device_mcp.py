"""Installation repair stays bounded, explicit and idempotent across hosts."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from device_mcp import DeviceMcpSetup


class DeviceMcpSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'device-tool'
        self.repo.mkdir()
        (self.repo / 'host.py').write_text('')
        self.registry = self.root / 'device-mcp.json'
        self.spec = {'schema_version': 1, 'name': 'device-tool', 'checkout': str(self.repo),
                     'entrypoint': 'host.py', 'env': {}}
        self.registry.write_text(json.dumps(self.spec))
        self.setup = DeviceMcpSetup(self.registry, 'codex')
        self.which = patch('device_mcp.shutil.which', return_value='/bin/tool')
        self.which.start()
        self.addCleanup(self.which.stop)

    def test_ready_environment_does_not_reinstall_or_register(self):
        with patch.object(self.setup, '_registration', return_value='registered'), \
             patch.object(self.setup, '_healthy', return_value=True), \
             patch.object(self.setup, '_install') as install, \
             patch.object(self.setup, '_register') as register:
            self.assertEqual(False, self.setup.ensure()['changed'])
        install.assert_not_called()
        register.assert_not_called()
        self.assertFalse(self.registry.with_suffix('.lock').exists())

    def test_missing_environment_syncs_lockfile_then_checks_health(self):
        with patch.object(self.setup, '_registration', return_value='registered'), \
             patch.object(self.setup, '_healthy', side_effect=[False, False, True, True]), \
             patch.object(self.setup, '_run') as run:
            self.assertTrue(self.setup.ensure()['changed'])
        command = run.call_args.args[0]
        self.assertEqual(['uv', 'sync', '--frozen', '--no-dev', '--python', '3.12'], command)
        self.assertEqual(str(self.repo), run.call_args.kwargs['cwd'])

    def test_missing_registration_is_added_once(self):
        with patch.object(self.setup, '_registration', side_effect=['missing_registration', 'missing_registration', 'registered']), \
             patch.object(self.setup, '_healthy', return_value=True), \
             patch.object(self.setup, '_register') as register:
            self.assertTrue(self.setup.ensure()['changed'])
        register.assert_called_once_with()

    def test_conflicting_user_registration_is_not_overwritten(self):
        with patch.object(self.setup, '_registration', return_value='registration_conflict'), \
             patch.object(self.setup, '_install') as install:
            with self.assertRaisesRegex(RuntimeError, 'registration_conflict'):
                self.setup.ensure()
        install.assert_not_called()

    def test_failed_health_is_reported_and_lock_released(self):
        with patch.object(self.setup, '_registration', return_value='registered'), \
             patch.object(self.setup, '_healthy', return_value=False), \
             patch.object(self.setup, '_run'):
            with self.assertRaisesRegex(RuntimeError, 'health check failed'):
                self.setup.ensure()
        self.assertFalse(self.registry.with_suffix('.lock').exists())

    def test_concurrent_setup_does_not_race_or_remove_other_lock(self):
        lock = self.registry.with_suffix('.lock')
        lock.write_text('')
        with patch.object(self.setup, 'status', return_value='missing_installation'), \
             patch.object(self.setup, '_install') as install:
            with self.assertRaisesRegex(RuntimeError, 'setup_busy'):
                self.setup.ensure()
        install.assert_not_called()
        self.assertTrue(lock.exists())

    def test_fresh_checkout_requires_approved_pinned_source(self):
        self.setup.checkout = self.root / 'missing'
        with patch.object(self.setup, '_run') as run:
            with self.assertRaisesRegex(ValueError, 'HTTPS repository'):
                self.setup._install()
            self.setup.spec['repository'] = 'https://example.org/device-tool.git'
            with self.assertRaisesRegex(ValueError, 'full pinned commit'):
                self.setup._install()
        run.assert_not_called()

    def test_missing_entrypoint_does_not_reset_existing_checkout(self):
        self.setup.entrypoint.unlink()
        with patch.object(self.setup, '_run') as run:
            with self.assertRaisesRegex(RuntimeError, 'not replaced'):
                self.setup._install()
        run.assert_not_called()

    def test_both_runtime_registration_commands_use_same_stdio_contract(self):
        for runtime in ('codex', 'claude'):
            self.setup.runtime = runtime
            with patch.object(self.setup, '_run') as run:
                self.setup._register()
            command = run.call_args.args[0]
            self.assertEqual(runtime, command[0])
            self.assertEqual(['--', str(self.setup.python), '-B', str(self.setup.entrypoint)], command[-4:])
            if runtime == 'claude':
                self.assertIn('--scope', command)
                self.assertIn('user', command)

    def test_codex_registration_is_checked_including_disabled_state(self):
        record = {'enabled': True, 'transport': {'type': 'stdio', **self.setup._expected()}}
        result = subprocess.CompletedProcess([], 0, json.dumps(record), '')
        with patch.object(self.setup, '_run', return_value=result):
            self.assertEqual('registered', self.setup._registration())
            record['enabled'] = False
            result.stdout = json.dumps(record)
            self.assertEqual('registration_conflict', self.setup._registration())

    def test_lookup_error_is_not_mistaken_for_missing_server(self):
        result = subprocess.CompletedProcess([], 1, '', 'invalid configuration')
        with patch.object(self.setup, '_run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'lookup failed'):
                self.setup._registration()

    def test_fresh_install_checks_out_exact_pin_without_shallow_clone(self):
        self.spec.update(checkout=str(self.root / 'fresh'),
                         repository='https://example.org/device-tool.git', revision='a' * 40)
        self.registry.write_text(json.dumps(self.spec))
        setup = DeviceMcpSetup(self.registry, 'codex')
        def execute(command, **kwargs):
            if command[0] == 'git' and 'checkout' in command:
                setup.checkout.mkdir()
                setup.entrypoint.write_text('')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(setup, '_run', side_effect=execute) as run, \
             patch.object(setup, '_healthy', side_effect=[False, True]):
            setup._install()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(['git', 'clone', '--no-checkout', self.spec['repository'], str(setup.checkout)], commands[0])
        self.assertEqual(['git', '-C', str(setup.checkout), 'checkout', '--detach', 'a' * 40], commands[1])
        self.assertEqual('uv', commands[2][0])

    def test_claude_user_registration_is_verified_without_model_cli(self):
        config = self.root / 'claude.json'
        config.write_text(json.dumps({'mcpServers': {self.setup.name: self.setup._expected()}}))
        self.setup.runtime = 'claude'
        self.setup.spec['claude_config'] = str(config)
        with patch.object(self.setup, '_run') as run:
            self.assertEqual('registered', self.setup._registration())
        run.assert_not_called()

    def test_registry_rejects_credentials_and_path_escape(self):
        for update in ({'env': {'API_KEY': 'fixture-only'}}, {'entrypoint': '../outside.py'}, {'health_imports': []}):
            self.registry.write_text(json.dumps({**self.spec, **update}))
            with self.assertRaises(ValueError):
                DeviceMcpSetup(self.registry, 'codex')


if __name__ == '__main__':
    unittest.main()
