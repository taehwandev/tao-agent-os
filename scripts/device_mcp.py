"""Prepare an operator-configured device MCP without adding per-task daemons."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit


class DeviceMcpSetup:
    """Own the local tool registry, bounded installation and host registration."""

    def __init__(self, registry: Path, runtime: str):
        self.registry = registry.expanduser().resolve()
        self.runtime = runtime
        if runtime not in {'codex', 'claude'}:
            raise ValueError('unsupported runtime')
        self.spec = json.loads(self.registry.read_text(encoding='utf-8'))
        if self.spec.get('schema_version') != 1:
            raise ValueError('unsupported device MCP registry schema')
        self.name = self.spec['name']
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', self.name):
            raise ValueError('invalid MCP name')
        self.checkout = Path(self.spec['checkout']).expanduser()
        if not self.checkout.is_absolute():
            raise ValueError('checkout must be an absolute operator-selected path')
        self.entrypoint = self.checkout / self.spec['entrypoint']
        self.entrypoint.resolve().relative_to(self.checkout.resolve())
        self.python = self.checkout / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.env = self.spec.get('env', {})
        if not isinstance(self.env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in self.env.items()):
            raise ValueError('env must contain string values')
        if any(re.search(r'KEY|TOKEN|SECRET|PASSWORD', k, re.I) for k in self.env):
            raise ValueError('device MCP registry must not contain credentials')
        self.modules = self.spec.get('health_imports', ['mcp'])
        if not isinstance(self.modules, list) or not self.modules or not all(isinstance(m, str) and re.fullmatch(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*', m) for m in self.modules):
            raise ValueError('health_imports must name Python modules')

    def _run(self, argv, *, check=True, cwd=None, timeout=60):
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(f'{Path(argv[0]).name} exited {result.returncode}')
        return result

    def _expected(self):
        return {'command': str(self.python), 'args': ['-B', str(self.entrypoint)], 'env': self.env}

    def _registration(self):
        return _host_registration(self)

    def _healthy(self):
        if not self.python.is_file() or not self.entrypoint.is_file():
            return False
        code = 'import importlib; [importlib.import_module(n) for n in ' + repr(self.modules) + ']'
        return self._run([str(self.python), '-I', '-B', '-c', code], check=False).returncode == 0

    def status(self):
        registration = self._registration()
        if registration in {'missing_runtime', 'registration_conflict'}:
            return registration
        if not self.checkout.is_dir():
            return 'missing_checkout'
        if not self._healthy():
            return 'missing_installation'
        return 'ready' if registration == 'registered' else registration

    def _install(self):
        if not self.checkout.exists():
            url = self.spec.get('repository', '')
            revision = self.spec.get('revision', '')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('fresh installation requires an operator-approved HTTPS repository')
            if not re.fullmatch(r'[0-9a-f]{40}', revision):
                raise ValueError('fresh installation requires a full pinned commit')
            self._run(['git', 'clone', '--no-checkout', url, str(self.checkout)], timeout=180)
            self._run(['git', '-C', str(self.checkout), 'checkout', '--detach', revision])
        if not self.entrypoint.is_file():
            raise RuntimeError('configured entrypoint missing; existing checkout was not replaced')
        if not self._healthy():
            if not shutil.which('uv'):
                raise RuntimeError('uv is required; use the approved platform installer')
            command = ['uv', 'sync', '--frozen', '--no-dev', '--python', self.spec.get('python_version', '3.12')]
            if self.python.exists():
                command.append('--reinstall')
            self._run(command, cwd=str(self.checkout), timeout=300)
            if not self._healthy():
                raise RuntimeError('installation health check failed')

    def _register(self):
        if self.runtime == 'codex':
            command = ['codex', 'mcp', 'add', self.name]
        else:
            command = ['claude', 'mcp', 'add', '--scope', 'user', '--transport', 'stdio', self.name]
        for key, value in self.env.items():
            command += ['--env', f'{key}={value}']
        self._run(command + ['--', str(self.python), '-B', str(self.entrypoint)])

    def ensure(self):
        state = self.status()
        if state == 'ready':
            return {'status': 'ready', 'changed': False, 'runtime': self.runtime}
        if state in {'missing_runtime', 'registration_conflict'}:
            raise RuntimeError(state)
        lock = self.registry.with_suffix('.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError('setup_busy; do not start a concurrent installer') from exc
        try:
            os.write(fd, str(os.getpid()).encode('ascii'))
            os.close(fd)
            self._install()
            registration = self._registration()
            if registration == 'missing_registration':
                self._register()
            elif registration != 'registered':
                raise RuntimeError(registration)
            if self.status() != 'ready':
                raise RuntimeError('registration verification failed')
            return {'status': 'ready', 'changed': True, 'runtime': self.runtime,
                    'next': 'Reconnect the host MCP client, then verify device evidence.'}
        finally:
            lock.unlink()


def _host_registration(self):
    if self.runtime == 'codex':
        if not shutil.which('codex'):
            return 'missing_runtime'
        result = self._run(['codex', 'mcp', 'get', self.name, '--json'], check=False)
        if result.returncode:
            # Only a confirmed absence is safe to add. Other CLI errors are blockers.
            if 'not found' in result.stderr.lower() or 'no mcp server named' in result.stderr.lower():
                return 'missing_registration'
            raise RuntimeError('Codex registration lookup failed')
        record = json.loads(result.stdout)
        if record.get('enabled') is False:
            return 'registration_conflict'
        record = record.get('transport', {})
    else:
        if not shutil.which('claude'):
            return 'missing_runtime'
        config = Path(self.spec.get('claude_config', str(Path.home() / '.claude.json'))).expanduser()
        data = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
        record = data.get('mcpServers', {}).get(self.name)
        if record is None:
            return 'missing_registration'
    expected = self._expected()
    if record.get('type', 'stdio') != 'stdio' or any(record.get(k, {} if k == 'env' else None) != v for k, v in expected.items()):
        return 'registration_conflict'
    return 'registered'


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'ensure'])
    parser.add_argument('--runtime', required=True, choices=['codex', 'claude'])
    parser.add_argument('--registry', type=Path, default=Path.home() / '.tao' / 'device-mcp.json')
    args = parser.parse_args(argv)
    try:
        setup = DeviceMcpSetup(args.registry, args.runtime)
        result = setup.ensure() if args.action == 'ensure' else {'status': setup.status(), 'runtime': args.runtime}
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}))
        return 1
    print(json.dumps(result))
    return 0 if result['status'] == 'ready' else 1
