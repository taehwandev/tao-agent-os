"""Derived reuse of machine review checks; attestation and ledger own proof."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_review_attestation import ReviewAttestation, _attestation_id, _record_shape_failures
from agent_route_state import route_fingerprint
from support.bounded_git import run_git


class ReviewReuse:
    """Cache only structure/workflow checks for identical commit review bytes.

    Owner: derived review acceleration. Imports: filesystem, Git reads and
    attestation/ledger readers. No authority, gate mutation, or test execution.
    Callers/tests: agent_review_hook and test_agent_review_reuse.
    """

    def __init__(self, args: Any, paths: list[str], subject: dict[str, Any]):
        self.args, self.paths, self.subject = args, paths, subject
        self.project, self.rules = args.project.resolve(), args.rules.resolve()
        self.evidence = args.evidence or self.project / '.tao' / 'preflight.json'
        self.path = self.project / '.tao' / 'review-checks-latest.json'
        self.before = self.capture()
        self.reused: dict[str, Any] | None = None

    @staticmethod
    def digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('oversized review receipt')
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError('invalid review receipt')
        return value

    @staticmethod
    def git(project: Path, *args: str) -> bytes:
        result = run_git(['git', *args], cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError('review snapshot unavailable')
        return result.stdout

    def capture(self) -> dict[str, Any] | None:
        return _capture(self)

    def load(self) -> dict[str, Any] | None:
        return _load(self)

    def complete(self, checks: dict[str, Any], failures: list[str]) -> None:
        if self.before is None:
            return
        if self.capture() != self.before:
            failures.append('reviewed bytes changed while the review hook was running')
            return
        if failures:
            return
        results = {name: checks[name] for name in ('structure_review', 'workflow_validate')}
        checks['review_checks'] = {
            'snapshot_sha256': self.digest(self.before), 'results_sha256': self.digest(results),
            'source_attestation': self.reused['attestation_id'] if self.reused else '',
        }

    def publish(self, checks: dict[str, Any]) -> None:
        if not checks.get('review_checks') or self.before is None:
            return
        try:
            if self.capture() != self.before:
                return
            attestation = self.read(ReviewAttestation.path(self.evidence))
            if attestation.get('review_checks') != checks['review_checks']:
                return
            atomic_write_json(self.path, {
                'schema_version': 1, 'snapshot': self.before,
                'checks': {name: checks[name] for name in ('structure_review', 'workflow_validate')},
                'evidence': self.evidence.resolve().relative_to(self.project / '.tao').as_posix(),
                'attestation_id': attestation['attestation_id'],
            })
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            pass


def _file_records(root: Path, paths: list[str], *, follow_rules: bool = False) -> dict[str, Any]:
    records: dict[str, Any] = {}
    budget = [0, 0]

    def regular(path: Path, info: os.stat_result) -> dict[str, Any]:
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('unsupported review file kind')
        budget[1] += info.st_size
        if budget[1] > 256 * 1024 * 1024:
            raise ValueError('review snapshot byte budget exceeded')
        data = path.read_bytes()
        return {'mode': '100755' if info.st_mode & 0o111 else '100644',
                'permissions': stat.S_IMODE(info.st_mode), 'sha256': hashlib.sha256(data).hexdigest(),
                'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

    if len(paths) > 10000:
        raise ValueError('review snapshot file budget exceeded')
    for relative in sorted(set(paths)):
        budget[0] += 1
        if budget[0] > 10000:
            raise ValueError('review snapshot file budget exceeded')
        path = root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('foreign snapshot path')
        path.parent.resolve().relative_to(root.resolve())
        if any(parent.is_symlink() for parent in (path.parent, *path.parent.parents) if parent != root and root in parent.parents):
            raise ValueError('symlinked review parent')
        try:
            info = path.lstat()
        except FileNotFoundError:
            records[relative] = None
            continue
        if not (follow_rules and stat.S_ISLNK(info.st_mode)):
            records[relative] = regular(path, info)
            continue
        target = path.resolve(strict=True)
        target_relative = target.relative_to(root.resolve()).as_posix()
        contents = {}
        pending = [target]
        while pending:
            candidate = pending.pop()
            budget[0] += 1
            if budget[0] > 10000:
                raise ValueError('review snapshot file budget exceeded')
            metadata = candidate.lstat()
            key = candidate.relative_to(target).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                contents[key] = {'directory': stat.S_IMODE(metadata.st_mode)}
                for child in candidate.iterdir():
                    if child.name == '__pycache__' or child.suffix in {'.pyc', '.pyo'}:
                        continue
                    if len(pending) + budget[0] >= 10000:
                        raise ValueError('review snapshot file budget exceeded')
                    pending.append(child)
            else:
                # Nested links are refused; there is no recursive alias graph.
                contents[key] = regular(candidate, metadata)
        records[relative] = {'link': os.readlink(path), 'target': target_relative,
                             'permissions': stat.S_IMODE(info.st_mode), 'contents': contents}
    return records


def _capture(reuse: ReviewReuse) -> dict[str, Any] | None:
    if reuse.subject.get('kind') != 'working-tree':
        return None
    try:
        head = reuse.git(reuse.project, 'rev-parse', '--verify', 'HEAD').decode().strip()
        names = reuse.git(reuse.project, 'diff', '--name-only', '-z', '--no-renames', 'HEAD', '--')
        names += reuse.git(reuse.project, 'ls-files', '--others', '--exclude-standard', '-z')
        changed = sorted(set(os.fsdecode(p) for p in names.split(b'\0') if p))
        files = _file_records(reuse.project, changed)
        staged = set(reuse.git(reuse.project, 'diff', '--cached', '--name-only', '-z', '--no-renames', 'HEAD', '--').split(b'\0'))
        index = reuse.git(reuse.project, 'ls-files', '--stage', '-z')
        indexed = set()
        for entry in index.split(b'\0'):
            if not entry:
                continue
            metadata, name = entry.split(b'\t', 1)
            indexed.add(name)
            mode, oid, stage = metadata.decode().split()
            if stage != '0':
                raise ValueError('unmerged review index')
            if name not in staged:
                continue
            record = files.get(os.fsdecode(name))
            if not record or record['mode'] != mode or record['blob'] != oid:
                raise ValueError('partially staged review bytes')
        if any(files.get(os.fsdecode(name)) is not None for name in staged - indexed if name):
            raise ValueError('staged deletion differs from working bytes')
        rules_names = reuse.git(reuse.rules, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
        rules_files = _file_records(reuse.rules, [os.fsdecode(p) for p in rules_names.split(b'\0') if p], follow_rules=True)
        checker = Path(__file__).resolve().parent
        checker_files = _file_records(checker, [p.relative_to(checker).as_posix() for p in checker.rglob('*.py')])
        return {
            'project': str(reuse.project), 'head': head, 'files': files,
            'scope': getattr(reuse.args, 'review_scope', 'working-tree'), 'paths': reuse.paths,
            'rules': str(reuse.rules), 'rules_head': reuse.git(reuse.rules, 'rev-parse', '--verify', 'HEAD').decode().strip(),
            'rules_sha256': reuse.digest(rules_files), 'checker_sha256': reuse.digest(checker_files),
            'python': sys.version,
            'limits': {name: getattr(reuse.args, name, default) for name, default in (
                ('max_source_file_lines', 500), ('max_function_lines', 120),
                ('max_added_lines', 300), ('max_changed_paths', 25),
            )},
        }
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def _load(reuse: ReviewReuse) -> dict[str, Any] | None:
    if reuse.before is None:
        return None
    try:
        command = (reuse.read(reuse.evidence).get('route') or {}).get('command')
        if command not in {'commit', 'git_commit'}:
            return None
        if reuse.git(reuse.project, 'diff', '--name-only', '-z') or reuse.git(reuse.project, 'ls-files', '--others', '--exclude-standard', '-z'):
            return None
        cached = reuse.read(reuse.path)
        if set(cached) != {'schema_version', 'snapshot', 'checks', 'evidence', 'attestation_id'}:
            return None
        if cached['schema_version'] != 1 or cached['snapshot'] != reuse.before:
            return None
        source = (reuse.project / '.tao' / cached['evidence']).resolve()
        source.relative_to(reuse.project / '.tao')
        attestation = reuse.read(ReviewAttestation.path(source))
        if _record_shape_failures(attestation) or _attestation_id(attestation) != cached['attestation_id']:
            return None
        if attestation['attestation_id'] != cached['attestation_id']:
            return None
        preflight = reuse.read(source)
        if Path(preflight['project']).resolve() != reuse.project or Path(preflight['rules']).resolve() != reuse.rules:
            return None
        if attestation['preflight_evidence'] != {'path': cached['evidence'], 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}:
            return None
        if attestation['route_fingerprint'] != route_fingerprint(preflight['route']) or attestation['agent_run_id'] != preflight.get('agent_run_id'):
            return None
        receipt = attestation.get('review_checks') or {}
        if receipt.get('snapshot_sha256') != reuse.digest(reuse.before) or receipt.get('results_sha256') != reuse.digest(cached['checks']):
            return None
        ledger = reuse.read(gate_evidence_path_for_preflight(source))
        if ledger.get('preflight_evidence_sha256') != attestation['preflight_evidence']['sha256'] or ledger.get('route_fingerprint') != attestation['route_fingerprint']:
            return None
        if ledger.get('schema_version') != 1 or Path(ledger.get('preflight_evidence', '')).resolve() != source:
            return None
        entry = next((e for e in reversed(ledger.get('entries') or []) if e.get('gate') == 'review hook'), {})
        if entry.get('status') != 'SUCCESS' or entry.get('source') != 'review':
            return None
        if any((entry.get('fields') or {}).get(k) != v for k, v in ReviewAttestation.ledger_fields(attestation).items()):
            return None
        checks = cached['checks']
        if set(checks) != {'structure_review', 'workflow_validate'} or checks['structure_review'].get('failures') != [] or checks['workflow_validate'].get('returncode') != 0:
            return None
        reuse.reused = cached
        return checks
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None
