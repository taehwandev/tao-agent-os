#!/usr/bin/env python3
"""Validate the reviewed React/RN external skill source manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT
    / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
)
ALLOWED_DISPOSITIONS = {"distilled", "source_only"}
# A repository is `content_verified` only when every manifest SKILL.md for that
# provider was found byte-identical at the pinned commit. When upstream has
# already moved past the reviewed content, the original commit is not
# recoverable from a snapshot directory, so the honest record is `unpinned`
# rather than a guess at whatever HEAD happens to be today.
UNPINNED_COMMIT = "unknown"
ALLOWED_PROVENANCE = {"content_verified", "unpinned"}
HEX_DIGITS = set("0123456789abcdef")


def _load_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_paths(source_root: Path) -> dict[str, str]:
    return {
        path.relative_to(source_root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(source_root.rglob("SKILL.md"))
    }


def _is_sha(value: str, length: int) -> bool:
    return len(value) == length and all(char in HEX_DIGITS for char in value)


def _repository_failures(repositories: dict[str, object]) -> list[str]:
    """Every provider must carry a checkable provenance record.

    The snapshot date and bundle README hash only say when the files were
    reviewed, never which upstream commit they came from. Without that pin a
    refresh cannot tell "upstream moved on" apart from "our copy was edited".
    """

    failures: list[str] = []
    for provider, record in repositories.items():
        if not isinstance(record, dict):
            failures.append(
                f"repository {provider} must be an object with url, commit, and provenance"
            )
            continue
        if not str(record.get("url", "")).startswith("https://"):
            failures.append(f"repository {provider} needs an https url")
        commit = str(record.get("commit", ""))
        provenance = str(record.get("provenance", ""))
        if provenance not in ALLOWED_PROVENANCE:
            failures.append(
                f"repository {provider} provenance must be content_verified or unpinned"
            )
        elif provenance == "unpinned" and commit != UNPINNED_COMMIT:
            failures.append(
                f"repository {provider} is unpinned and must record commit {UNPINNED_COMMIT}"
            )
        elif provenance == "content_verified" and not _is_sha(commit, 40):
            failures.append(
                f"repository {provider} must pin a full 40-character commit sha"
            )
        if not str(record.get("verified_at", "")).strip():
            failures.append(f"repository {provider} needs a verified_at date")
    return failures


def _manifest_failures(payload: dict[str, object], repo_root: Path) -> list[str]:
    entries = payload.get("skills", [])
    snapshot = payload.get("snapshot", {})
    repositories = payload.get("repositories", {})
    failures: list[str] = []
    if (
        payload.get("schema_version") != 1
        or not isinstance(entries, list)
        or not isinstance(snapshot, dict)
        or not isinstance(repositories, dict)
    ):
        return [
            "manifest must use schema_version 1 with snapshot, repositories, and skills"
        ]
    failures.extend(_repository_failures(repositories))
    paths = [
        str(entry.get("path", "")) for entry in entries if isinstance(entry, dict)
    ]
    if len(entries) != 41 or len(paths) != len(set(paths)):
        failures.append("manifest must contain 41 unique SKILL.md paths")
    if paths != sorted(paths):
        failures.append("manifest SKILL.md paths must stay sorted")
    installable = sum(
        bool(entry.get("installable")) for entry in entries if isinstance(entry, dict)
    )
    if installable != 32:
        failures.append("manifest must identify exactly 32 installable skills")
    provider_counts = {
        provider: sum(
            bool(entry.get("installable")) and entry.get("provider") == provider
            for entry in entries
            if isinstance(entry, dict)
        )
        for provider in repositories
    }
    if provider_counts != {
        "vercel": 4,
        "expo": 20,
        "callstack": 7,
        "software_mansion": 1,
    }:
        failures.append(
            "installable provider counts must remain Vercel 4, Expo 20, "
            "Callstack 7, Software Mansion 1"
        )
    expected_snapshot = {
        "installable_skills": 32,
        "nested_skills": 9,
        "skill_files": 41,
    }
    if any(snapshot.get(key) != value for key, value in expected_snapshot.items()):
        failures.append("snapshot counts must declare 32 installable, 9 nested, and 41 total")
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append("every skill entry must be an object")
            continue
        path = str(entry.get("path", ""))
        if (
            not path.endswith("/SKILL.md")
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            failures.append(f"invalid skill path: {path or '<empty>'}")
        if entry.get("disposition") not in ALLOWED_DISPOSITIONS:
            failures.append(f"invalid disposition for {path}")
        if entry.get("provider") not in repositories:
            failures.append(f"unknown provider for {path}")
        if not str(entry.get("surface", "")).strip():
            failures.append(f"missing surface for {path}")
        sha256 = str(entry.get("sha256", ""))
        if len(sha256) != 64 or any(
            char not in "0123456789abcdef" for char in sha256
        ):
            failures.append(f"invalid sha256 for {path}")
        owners = entry.get("owners", [])
        if not isinstance(owners, list) or not owners:
            failures.append(f"missing owners for {path}")
        else:
            for owner in owners:
                if not (repo_root / str(owner)).is_file():
                    failures.append(f"missing owner for {path}: {owner}")
    return failures


def _remote_head(url: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    head = result.stdout.split()[0]
    return head if _is_sha(head, 40) else None


def _remote_failures(repositories: dict[str, object]) -> list[str]:
    """Compare each pinned commit with the provider's current remote HEAD.

    A moved HEAD is reported, not failed: a snapshot is a point in time and
    upstream is expected to advance. What does fail is being unable to answer
    the question at all -- an unpinned provider or an unreachable remote.
    """

    failures: list[str] = []
    for provider in sorted(repositories):
        record = repositories[provider]
        if not isinstance(record, dict):
            failures.append(f"remote check skipped: {provider} has no repository record")
            continue
        url = str(record.get("url", ""))
        commit = str(record.get("commit", ""))
        if commit == UNPINNED_COMMIT:
            failures.append(
                f"remote check cannot prove {provider}: no pinned commit, so a "
                "drifted upstream is indistinguishable from a locally edited snapshot"
            )
            continue
        head = _remote_head(url)
        if head is None:
            failures.append(f"remote check could not reach {provider} at {url}")
        elif head == commit:
            print(f"CURRENT: {provider} remote HEAD still matches the pinned commit")
        else:
            print(
                f"MOVED: {provider} remote HEAD is {head}; the snapshot stays "
                f"proven at {commit}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument(
        "--remote-check",
        action="store_true",
        help=(
            "compare each pinned commit with the provider's current remote HEAD; "
            "requires network access and is never run by the default offline check"
        ),
    )
    args = parser.parse_args(argv)
    payload = _load_manifest(args.manifest.resolve())
    failures = _manifest_failures(payload, ROOT)
    if args.source_root:
        source_root = args.source_root.resolve()
        actual = _source_paths(source_root)
        expected = {
            str(entry["path"]): str(entry["sha256"])
            for entry in payload["skills"]
            if isinstance(entry, dict)
        }
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        changed = sorted(
            path
            for path in set(expected) & set(actual)
            if expected[path] != actual[path]
        )
        failures.extend(f"missing source skill: {path}" for path in missing)
        failures.extend(f"unexpected source skill: {path}" for path in unexpected)
        failures.extend(f"source skill hash changed: {path}" for path in changed)
    if args.remote_check:
        repositories = payload.get("repositories", {})
        if isinstance(repositories, dict):
            failures.extend(_remote_failures(repositories))
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(
        "OK: React/RN external skill manifest covers "
        f"{len(payload['skills'])} SKILL.md files (32 installable, 9 nested)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
