"""Reusing a built document graph, and knowing when it may not be reused.

Owner: the document graph's persistence boundary.
Allowed imports: the standard library, and the surface-rules constant that
names the second input. This module must not import the builder it caches, or
the two would be a cycle; it reads the builder's source as bytes instead.
Callers/tests: ``workflow_doc_graph_build``; coverage lives in
``tests/test_workflow_doc_graph_cache.py``.
Verification: run that module's invalidation tests, each of which changes one
input and asserts the graph is rebuilt.

Every hook that validates a workflow builds the graph, and each hook is its own
process, so a per-process cache never helped the next one. Storing it is the
easy half. The hard half is the key, which must measure every input the build
reads, by the same route the build reads it -- three separate stale-hit classes
were found in review before this list was complete:

* the guidance documents, followed through symlinks because the build follows
  them;
* the surface rules file, which contributes doc-set and path-surface edges;
* the source of every project-local module the builder imports, so a graph
  built by older code is never served.

That last list is computed rather than written down. A hand-maintained one had
already drifted past four of its nine modules when this was split out.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

from workflow_doc_surfaces import RULES_FILE

CACHE_GENERATIONS = 3
BUILDER_ENTRY_POINT = "workflow_doc_graph_build"
SCRIPTS_ROOT = Path(__file__).resolve().parent


def document_key(root: Path, docs: set[str]) -> str:
    """Digest every input the graph is built from, and nothing else.

    Keyed on the inputs rather than on the worktree, because a worktree
    signature changes with every source edit -- and between a start and the
    review that follows it, an agent has edited source. A key that tracks the
    inputs is a key that can hit.

    The inputs are the guidance documents *and* the surface rules file, which
    contributes the `doc_set`, request-intent and path-surface edges. Leaving
    it out was a stale hit: changing only the rules file changed the graph and
    not the key.

    Size and modification time rather than content: reading the 2 MB the build
    reads is the cost the cache exists to avoid.
    """

    digest = hashlib.sha256()
    digest.update(_builder_digest().encode("ascii"))
    for rel in [*sorted(docs), RULES_FILE]:
        path = root / rel
        try:
            # Follow the link: the build reads through it, so the key must
            # measure what the build reads. Two tracked documents in this
            # repository are symlinks into a pruned directory, whose targets
            # a walk never visits -- with `lstat` here, editing one of those
            # targets changed the graph and not the key.
            stat = path.stat()
            # Where it points is part of the input too, in case a retarget
            # lands on a file with the same size and time. Read inside the
            # same guard: a link can vanish between the two calls, and this
            # function may never be the reason a build fails.
            link = os.readlink(path) if path.is_symlink() else ""
        except FileNotFoundError:
            # A project may have no surface rules, and a document may be a
            # broken link the build skips. Both are states the graph depends
            # on, and neither is a reason to stop caching.
            digest.update(rel.encode("utf-8", "surrogateescape"))
            digest.update(b"\0absent\0")
            continue
        except OSError:
            return ""
        digest.update(rel.encode("utf-8", "surrogateescape"))
        digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode("ascii"))
        if link:
            digest.update(b"\0link\0")
            digest.update(link.encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def _builder_modules() -> tuple[str, ...]:
    """Every project-local module the builder imports, found by reading it.

    Written down, this list drifted past four of its nine entries within a
    day -- including the module that supplies the walk and the one that
    supplies the helper the edge grouping calls. Reading the imports costs a
    parse of about nine small files, once per process, and cannot be forgotten.
    """

    seen: set[str] = set()
    queue = [BUILDER_ENTRY_POINT]
    found: list[str] = []
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        source = SCRIPTS_ROOT / (name.replace(".", "/") + ".py")
        if not source.is_file():
            # Standard library and anything outside this package: not ours to
            # version, and the interpreter is not part of the graph.
            continue
        found.append(name)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                queue.append(node.module)
    return tuple(sorted(found))


@lru_cache(maxsize=1)
def _builder_digest() -> str:
    """Digest the code that produces the graph, so a change to it invalidates.

    Content rather than modification time: a checkout that rewrites these
    files without changing them should not throw the cache away.
    """

    digest = hashlib.sha256()
    for name in _builder_modules():
        source = SCRIPTS_ROOT / (name.replace(".", "/") + ".py")
        try:
            digest.update(source.read_bytes())
        except OSError:
            return "unversioned"
    return digest.hexdigest()


def _cache_directory(root: Path) -> Path | None:
    """The run-state cache, only where run state already exists.

    `.tao` carries its own ignore file, so writing under it stays out of the
    repository. A project that has never run a hook has no `.tao`, and creating
    one here could put a 750 KB file into someone's next commit.
    """

    state = root / ".tao"
    return state / "cache" / "doc-graph" if state.is_dir() else None


def read_cached_graph(root: Path, key: str) -> dict[str, list[dict[str, object]]] | None:
    directory = _cache_directory(root)
    if not key or directory is None:
        return None
    try:
        payload = json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_cached_graph(root: Path, key: str, graph: dict[str, list[dict[str, object]]]) -> None:
    """Store this generation, and keep the cache from growing without bound."""

    directory = _cache_directory(root)
    if not key or directory is None:
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"{key}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(graph, sort_keys=True), encoding="utf-8")
        temporary.replace(directory / f"{key}.json")
        _prune_cache(directory)
    except OSError:
        # A cache that cannot be written is a build, not a failure.
        return


def _prune_cache(directory: Path) -> None:
    generations = sorted(
        directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for stale in generations[CACHE_GENERATIONS:]:
        try:
            stale.unlink()
        except OSError:
            continue
