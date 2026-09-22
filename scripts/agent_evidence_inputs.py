"""Content identities for explicitly scoped, revision-independent local checks.

Owner: bounded input capture. Allowed: filesystem and read-only Git listing.
Forbidden: authority, ledger writes, subprocess execution of checked programs.
Caller: GateEvidenceReuse; tests: test_agent_gate_reuse.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from agent_worktree_fingerprint import git_output


class EvidenceInputs:
    """Hash declared files, or every non-ignored project file, without Git writes."""

    @staticmethod
    def matches(snapshot: dict, project: Path, rules: Path) -> bool:
        try:
            return (
                snapshot.get("project") == str(project)
                and snapshot.get("rules") == str(rules)
                and snapshot.get("states") == {
                    "project": EvidenceInputs.capture(project, snapshot["input_paths"]),
                    "rules": EvidenceInputs.capture(rules, []),
                }
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return False

    @staticmethod
    def capture(root: Path, paths: list[str]) -> str:
        if not isinstance(paths, list) or len(paths) > 5000 or any(
            not isinstance(path, str) or not path for path in paths
        ):
            raise ValueError("input_paths must be a bounded list of relative files")
        selected = paths or sorted(set(git_output(
            root, "ls-files", "--cached", "--others", "--exclude-standard", "-z",
        ).split("\0")) - {""})
        if len(selected) > 5000:
            raise ValueError("input snapshot exceeds file limit")
        digest = hashlib.sha256()
        total = 0
        for relative in sorted(set(selected)):
            path = root / relative
            if Path(relative).is_absolute() or ".." in Path(relative).parts or ".git" in Path(relative).parts:
                raise ValueError("input path must stay inside the project")
            if path.is_symlink():
                # A listed symlink is identified by the target it names, exactly
                # as Git stores it, and is never followed. Refusing it instead
                # made every repository that holds one -- this one holds five --
                # fall back to the whole-revision snapshot without saying so, so
                # a declared dependency set could never actually be reused.
                digest.update(json.dumps([relative, "symlink", os.readlink(path)]).encode())
                continue
            if path.resolve() != path or not path.is_relative_to(root):
                raise ValueError("input path reached through a symlinked parent cannot be reused")
            try:
                before = path.stat()
            except FileNotFoundError:
                # Explicit missing inputs represent absence, not an empty file.
                if paths:
                    digest.update(json.dumps([relative, "missing"]).encode())
                continue
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("input paths must name regular files, not directories or submodules")
            total += before.st_size
            if total > 256 * 1024 * 1024:
                raise ValueError("input snapshot exceeds byte limit")
            contents = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    contents.update(block)
            after = path.stat()
            # Reading may update atime itself; only identity, metadata and write
            # timestamps signal that the captured input changed underneath us.
            stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(getattr(after, field) != getattr(before, field) for field in stable_fields):
                raise ValueError("input changed during capture")
            digest.update(json.dumps([relative, stat.S_IMODE(before.st_mode), contents.hexdigest()]).encode())
        return digest.hexdigest()

    @staticmethod
    def valid_record(snapshot: dict, evidence: Path) -> bool:
        if not snapshot:
            return True
        if not isinstance(snapshot, dict):
            return False
        if snapshot.get("schema_version") == 1:
            return True  # Legacy snapshots remain revision-sensitive at reuse.
        if snapshot.get("schema_version") != 2:
            return False
        try:
            current = json.loads(evidence.read_text(encoding="utf-8"))
            return EvidenceInputs.matches(snapshot, Path(current["project"]), Path(current["rules"]))
        except (OSError, ValueError, KeyError, TypeError):
            return False
