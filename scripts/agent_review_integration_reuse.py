"""Find attested pre-commit checks in registered worktrees of the same repo."""

from copy import copy
from pathlib import Path


def reuse_committed_review(reuse, validate):
    """Reuse machine checks only; target review still owns authority and audit.

    owner: exact single-commit review matching; allowed imports: receipt reader
    and validator supplied by ReviewReuse; forbidden imports: gate mutation or
    external services; callers/tests: ReviewReuse and integration reuse tests;
    verification: immutable commit bytes plus original attestation and ledger.
    """
    try:
        listing = reuse.git(reuse.project, 'worktree', 'list', '--porcelain', '-z')
        roots = [Path(part[9:].decode()).resolve() for part in listing.split(b'\0') if part.startswith(b'worktree ')]
        if len(roots) > 64:
            return None
        current = reuse.before
        for root in roots:
            try:
                path = root / '.tao' / 'review-checks-latest.json'
                cached = reuse.read(path)
                snapshot = cached['snapshot']
                if snapshot.get('project') != str(root) or snapshot.get('scope') != 'working-tree':
                    continue
                if snapshot.get('head') != current['base']:
                    continue
                # Empty paths means the whole diff; partial reviews cannot
                # authorize omitted files just because their bytes were hashed.
                if snapshot.get('paths') and sorted(snapshot['paths']) != sorted(current['files']):
                    continue
                ignored = {'project', 'head', 'scope', 'paths', 'base'}
                if {k: v for k, v in snapshot.items() if k not in ignored} != {k: v for k, v in current.items() if k not in ignored}:
                    continue
                candidate = copy(reuse)
                candidate.project, candidate.path = root, path
                candidate.before, candidate.subject = snapshot, {'kind': 'working-tree'}
                checks = validate(candidate, require_fully_staged=False, require_commit_route=False)
                if checks is not None:
                    reuse.reused = candidate.reused
                    return checks
            except (OSError, ValueError, TypeError, KeyError):
                continue
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        pass
    return None
