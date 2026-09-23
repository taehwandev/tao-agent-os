"""Derived reuse of machine review checks; attestation and ledger own proof."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_review_attestation import ReviewAttestation, _attestation_id, _record_shape_failures
from agent_route_state import route_fingerprint
from support.bounded_git import run_git
from support.stage_timing import stage
from agent_review_integration_reuse import reuse_committed_review


# A file whose last change is this close to the moment it was hashed is "racy"
# in Git's sense: a later write could land in the same timestamp tick and leave
# every stat field unchanged. Such files are never memoized. Two seconds covers
# the coarsest common timestamp granularity (FAT) with room to spare.
RACY_WINDOW_NS = 2_000_000_000


class ReviewReuse:
    """Cache structure/workflow checks for identical reviewed bytes.

    Owner: derived review acceleration. Imports: filesystem, Git reads and
    attestation/ledger readers. No authority, gate mutation, or test execution.
    Callers/tests: agent_review_hook and test_agent_review_reuse.
    """

    def __init__(self, args: Any, paths: list[str], subject: dict[str, Any]):
        self.args, self.paths, self.subject = args, paths, subject
        self.project, self.rules = args.project.resolve(), args.rules.resolve()
        self.evidence = args.evidence or self.project / '.tao' / 'preflight.json'
        self.path = self.project / '.tao' / 'review-checks-latest.json'
        # complete() captures again to prove nothing moved while the hook ran.
        # Rules and checker files are ~1100 unchanged reads the second time, so
        # it reuses their hashes while every stat field still matches.
        self.hash_memo: dict[tuple[Any, ...], dict[str, Any]] = {}
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
        with stage('review_snapshot'):
            return _capture(self)

    def load(self, *, require_fully_staged: bool = True, require_commit_route: bool = True) -> dict[str, Any] | None:
        with stage('review_reuse_lookup'):
            return _load(self, require_fully_staged=require_fully_staged, require_commit_route=require_commit_route)

    @classmethod
    def publication_candidate(cls, evidence: Path) -> dict[str, Any] | None:
        """Describe exact prior review coverage before publication staging.

        The result is advisory. The review hook still performs its staged-scope
        and drift checks after staging; any mismatch falls back to full review.
        """
        return _publication_candidate(cls, evidence)

    def complete(self, checks: dict[str, Any], failures: list[str]) -> None:
        if self.before is None:
            return
        after = self.capture()
        if after != self.before:
            checks['review_snapshot_stability'] = {
                'status': 'FAIL',
                'snapshot_available': after is not None,
                'changed_fields': sorted(
                    key for key in self.before if after is not None and self.before[key] != after.get(key)
                ),
            }
            failures.append('reviewed bytes changed while the review hook was running')
            return
        if failures:
            return
        results = _reusable_checks(checks)
        checks['review_checks'] = {
            'snapshot_sha256': self.digest(self.before), 'results_sha256': self.digest(results),
            'source_attestation': self.reused['attestation_id'] if self.reused else '',
        }

    def publish(self, checks: dict[str, Any]) -> None:
        if not checks.get('review_checks') or self.before is None:
            return
        try:
            # This is a derived cache, not current-run proof. complete() already
            # checked stability; a later change makes the consumer snapshot miss.
            attestation = self.read(ReviewAttestation.path(self.evidence))
            if attestation.get('review_checks') != checks['review_checks']:
                return
            atomic_write_json(self.path, {
                'schema_version': 2, 'snapshot': self.before,
                'checks': _reusable_checks(checks),
                'evidence': self.evidence.resolve().relative_to(self.project / '.tao').as_posix(),
                'attestation_id': attestation['attestation_id'],
            })
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            pass


def _publication_candidate(
    reuse_type: type[ReviewReuse],
    evidence: Path,
) -> dict[str, Any] | None:
    try:
        preflight = reuse_type.read(evidence)
        if ((preflight.get('route') or {}).get('command') not in {'commit', 'git_commit'}
                and not (preflight.get('work') or {}).get('previous_action')):
            return None
        project = Path(preflight['project']).resolve()
        rules = Path(preflight['rules']).resolve()
        evidence.resolve().relative_to(project / '.tao' / 'runs')
        cached = reuse_type.read(project / '.tao' / 'review-checks-latest.json')
        snapshot = cached.get('snapshot')
        if not isinstance(snapshot, dict):
            return None
        paths = snapshot.get('paths')
        limits = snapshot.get('limits')
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            return None
        expected_limits = {
            'max_source_file_lines', 'max_function_lines',
            'max_added_lines', 'max_changed_paths',
        }
        if not isinstance(limits, dict) or set(limits) != expected_limits:
            return None
        args = SimpleNamespace(
            project=project,
            rules=rules,
            evidence=evidence,
            review_scope=snapshot.get('scope', 'working-tree'),
            **limits,
        )
        reuse = reuse_type(args, paths, {'kind': 'working-tree'})
        if reuse.load(require_fully_staged=False) is None or reuse.before is None:
            return None
        return {
            'scope': reuse.before['scope'],
            'changed_paths': sorted(reuse.before['files']),
        }
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _file_records(
    root: Path,
    paths: list[str],
    *,
    follow_rules: bool = False,
    memo: dict[tuple[Any, ...], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    resolved_root = root.resolve()
    budget = [0, 0]

    def regular(path: Path, info: os.stat_result) -> dict[str, Any]:
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('unsupported review file kind')
        budget[1] += info.st_size
        if budget[1] > 256 * 1024 * 1024:
            raise ValueError('review snapshot byte budget exceeded')
        # ctime is in the key because no caller can set it back: any write, or
        # a utime that restores mtime, moves it and so misses the memo.
        key = (str(path), info.st_dev, info.st_ino, info.st_mode, info.st_size,
               info.st_mtime_ns, info.st_ctime_ns)
        if memo is not None and key in memo:
            return dict(memo[key])
        hashed_at = time.time_ns()
        data = path.read_bytes()
        record = {'mode': '100755' if info.st_mode & 0o111 else '100644',
                  'permissions': stat.S_IMODE(info.st_mode), 'sha256': hashlib.sha256(data).hexdigest(),
                  'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}
        if memo is not None and max(info.st_mtime_ns, info.st_ctime_ns) < hashed_at - RACY_WINDOW_NS:
            memo[key] = dict(record)
        return record

    if len(paths) > 10000:
        raise ValueError('review snapshot file budget exceeded')
    for relative in sorted(set(paths)):
        budget[0] += 1
        if budget[0] > 10000:
            raise ValueError('review snapshot file budget exceeded')
        path = root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('foreign snapshot path')
        path.parent.resolve().relative_to(resolved_root)
        if _symlinked_parent(root, path):
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
        target_relative = target.relative_to(resolved_root).as_posix()
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


def _symlinked_parent(root: Path, path: Path) -> bool:
    """Whether a directory between ``root`` (exclusive) and ``path`` is a symlink.

    ``path`` is ``root / relative`` with no ``..`` and no absolute part, so its
    lexical ancestors reach ``root`` exactly. Walking up to it checks the same
    directories as testing ``root in parent.parents`` for each ancestor, in one
    pass instead of rebuilding every ancestor chain for every file.
    """
    parent = path.parent
    while parent != root and parent != parent.parent:
        if parent.is_symlink():
            return True
        parent = parent.parent
    return False


def _capture(reuse: ReviewReuse) -> dict[str, Any] | None:
    kind = reuse.subject.get('kind')
    if kind not in {'working-tree', 'commit-range'}:
        return None
    try:
        head = reuse.git(reuse.project, 'rev-parse', '--verify', 'HEAD').decode().strip()
        if kind == 'commit-range':
            base = reuse.subject['base_sha']
            if head != reuse.subject['head_sha'] or reuse.git(reuse.project, 'status', '--porcelain'):
                return None
            if reuse.git(reuse.project, 'rev-list', '--parents', '-n', '1', head).decode().split() != [head, base]:
                return None
            names = reuse.git(reuse.project, 'diff', '--name-only', '-z', '--no-renames', base, head, '--')
        else:
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
        memo = getattr(reuse, 'hash_memo', None)
        rules_files = _file_records(reuse.rules, [os.fsdecode(p) for p in rules_names.split(b'\0') if p],
                                    follow_rules=True, memo=memo)
        checker = Path(__file__).resolve().parent
        checker_files = _file_records(checker, [p.relative_to(checker).as_posix() for p in checker.rglob('*.py')],
                                      memo=memo)
        return {
            **({'base': base} if kind == 'commit-range' else {}),
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
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return None


def _load(
    reuse: ReviewReuse,
    *,
    require_fully_staged: bool = True,
    require_commit_route: bool = True,
) -> dict[str, Any] | None:
    if reuse.before is None:
        return None
    try:
        current = reuse.read(reuse.evidence)
        command = (current.get('route') or {}).get('command')
        linked = bool((current.get('work') or {}).get('previous_action'))
        if require_commit_route and command not in {'commit', 'git_commit'} and not linked:
            return None
        if reuse.subject.get('kind') == 'commit-range':
            return reuse_committed_review(reuse, _load)
        needs_staging = require_fully_staged and not (
            linked and require_commit_route and command not in {'commit', 'git_commit'}
        )
        if needs_staging and (
            reuse.git(reuse.project, 'diff', '--name-only', '-z')
            or reuse.git(reuse.project, 'ls-files', '--others', '--exclude-standard', '-z')
        ):
            return None
        cached = reuse.read(reuse.path)
        if set(cached) != {'schema_version', 'snapshot', 'checks', 'evidence', 'attestation_id'}:
            return None
        if cached['schema_version'] not in {1, 2} or cached['snapshot'] != reuse.before:
            return None
        source = (reuse.project / '.tao' / cached['evidence']).resolve()
        source.relative_to(reuse.project / '.tao')
        attestation = reuse.read(ReviewAttestation.path(source))
        if _record_shape_failures(attestation) or _attestation_id(attestation) != cached['attestation_id']:
            return None
        if attestation['attestation_id'] != cached['attestation_id']:
            return None
        preflight = reuse.read(source)
        if linked and (
            (current.get('work') or {}).get('id') != (preflight.get('work') or {}).get('id', preflight.get('agent_run_id'))
            or not (current.get('runtime_session') or {}).get('session_id')
            or current.get('runtime_session') != preflight.get('runtime_session')
        ):
            return None
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
        expected = {'structure_review', 'workflow_validate'}
        if cached['schema_version'] == 2:
            expected.add('review_input')
        if set(checks) != expected or checks['structure_review'].get('failures') != [] or checks['workflow_validate'].get('returncode') != 0:
            return None
        reuse.reused = cached
        return checks
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _reusable_checks(checks: dict[str, Any]) -> dict[str, Any]:
    """Bind review narratives to the same attested digest as machine results."""
    return {
        **{name: checks[name] for name in ('structure_review', 'workflow_validate')},
        'review_input': {name: str(checks.get(name) or '') for name in (
            'code_review_evidence', 'docs_freshness_evidence',
            'structure_review_evidence', 'boundary_plan_evidence',
            'side_effect_audit_evidence',
        )},
    }
