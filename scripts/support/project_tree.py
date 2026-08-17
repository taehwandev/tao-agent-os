"""One rule for which directories a repository-wide walk must not enter.

Owner: the repository-walk boundary.
Allowed imports: standard-library path and filesystem utilities only.
Forbidden imports: workflow routing, agent lifecycle, gate policy, or any
project-specific rule -- this module decides where a walk goes, never what a
caller does with what it finds.
Callers/tests: the document-graph build, the markdown validator, and the skill
catalogue; coverage lives in ``tests/test_support_project_tree.py``.
Verification: run that module's pruning and caller-result tests, which compare
each converted caller against the result it produced before.

Every walk here filtered its unwanted results *after* finding them, so the
walker still descended into the project state directory -- which holds one
directory per run and, in an integrated checkout, a whole second copy of the
repository. The document graph walked 885 markdown files to keep 495; the
skill catalogue walked 320 skill documents to keep 159. The cost is paid by
whoever is waiting: the document graph is built inside workflow validation,
which the review hook runs before it can report.

Pruning at the directory is the same answer computed once. It is only the same
answer while the pruned set stays a subset of what each caller already
discarded, which is why what to prune is the caller's to name: `.tao` is not
uniformly disposable -- `.tao/skills/` is tracked content its own `.gitignore`
deliberately keeps -- so a caller that wants those documents prunes
`.tao/runs` and a caller that wants none of `.tao` prunes all of it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


# What every caller here already discards: project state and the repository's
# own storage. A caller that wants part of `.tao` names a narrower set.
PRUNED_DIRECTORIES = frozenset({".tao", ".git"})
# For callers that want `.tao/skills` but not one directory per run.
PRUNED_RUN_STATE = frozenset({".git", ".tao/runs"})


def iter_project_files(
    root: Path,
    name: str = "",
    *,
    pruned: frozenset[str] = PRUNED_DIRECTORIES,
) -> Iterator[Path]:
    """Yield files under ``root``, never descending into a pruned directory.

    An entry in ``pruned`` is a bare directory name, pruned wherever it
    appears, or a root-relative POSIX path, pruned only at that exact place --
    `.tao` excludes project state everywhere, `.tao/runs` excludes only the
    run directories while leaving the tracked skills beside them.

    ``name`` selects by exact file name when given, and by suffix when it
    starts with ``*``; an empty name yields every file. Symlinked directories
    are not followed, matching ``Path.rglob``, so a link cannot walk a caller
    out of the tree it asked about.

    Only files are yielded, which is the one way this differs from ``rglob``:
    that also returns a *directory* whose name matches, so a directory called
    ``notes.md`` used to enter the document graph as a node whose contents
    could never be read. Every caller here wants documents, so the difference
    is deliberate -- and stated, because a silent one is how a rewrite that
    promised the same answer stops giving it.
    """

    root = Path(root)
    suffix = name[1:] if name.startswith("*") else ""
    for base, directories, files in os.walk(root, followlinks=False):
        here = Path(base)
        directories[:] = [
            item
            for item in directories
            if item not in pruned
            and (here / item).relative_to(root).as_posix() not in pruned
        ]
        for file_name in files:
            if name and not (
                file_name.endswith(suffix) if suffix else file_name == name
            ):
                continue
            yield here / file_name
