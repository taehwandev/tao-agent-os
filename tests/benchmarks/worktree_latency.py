"""Compare one frozen patch in a branch checkout and a linked worktree.

Owner: offline checkout/worktree latency measurements for the README audit.
Allowed imports: Python 3.9 standard library; subprocesses: Git and focused tests.
Forbidden effects: live repository writes, global settings, hooks, network/model calls.
Verification: identical patch, focused test counts and final tracked content.
Run manually; measurements exclude Codex/model/tool transport and dependency setup.
"""
import argparse
import hashlib
import io
import json
import math
import os
import platform
import re
import statistics
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
BASE = "22c1ea9fdae901bb23540193c84a8c2579db6e7f"
FEATURE = "63f6c1d05f3a76e984f3d95961a51066b6564db1"
TESTS = ("test_codex_approval_setup.py", "test_codex_setup.py")
PHASES = ("prepare", "patch", "tests", "commit", "integration", "total")


def run(argv, cwd=None, env=None, data=None):
    result = subprocess.run(argv, cwd=cwd, env=env, input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("Benchmark subprocess failed (exit %s)" % result.returncode)
    return result.stdout, result.stderr


def git(root, *args, env=None, data=None):
    return run(["git", "-C", str(root), *args], env=env, data=data)[0]


def duration(action):
    started = time.perf_counter_ns()
    result = action()
    return (time.perf_counter_ns() - started) / 1e6, result


def archive_files(archive):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
                raise ValueError("Unsafe archive member")
            if member.isdir():
                continue
            if member.name in files:
                raise ValueError("Duplicate archive member: " + member.name)
            if member.issym():
                link = Path(member.linkname)
                target = Path(os.path.normpath(str(path.parent / link)))
                if link.is_absolute() or target.is_absolute() or ".." in target.parts:
                    raise ValueError("Escaping archive link: " + member.name)
                files[member.name] = (os.fsencode(member.linkname), 2)
                continue
            if not member.isfile():
                raise ValueError("Unsupported archive member: " + member.name)
            content = source.extractfile(member)
            if content is None:
                raise ValueError("Missing archive content")
            files[member.name] = (content.read(), int(bool(member.mode & 0o111)))
    links = {Path(name) for name, (_, mode) in files.items() if mode == 2}
    if any(parent in links for name in files for parent in Path(name).parents):
        raise ValueError("Archive member would be written through a link")
    return files


def content_digest(files):
    digest = hashlib.sha256()
    for name, (data, mode) in sorted(files.items()):
        digest.update(name.encode() + b"\0" + bytes([mode]))
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def isolated_env(root):
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GIT_") or key in ("PYTHONPATH", "PYTHONHOME"):
            del env[key]
    for name in ("home", "tmp", "cache", "config", "data"):
        (root / name).mkdir()
    env.update(HOME=str(root / "home"), TMPDIR=str(root / "tmp"),
               XDG_CACHE_HOME=str(root / "cache"), XDG_CONFIG_HOME=str(root / "config"),
               XDG_DATA_HOME=str(root / "data"), PYTHONDONTWRITEBYTECODE="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="Benchmark",
               GIT_COMMITTER_NAME="Benchmark", GIT_AUTHOR_EMAIL="bench@example.invalid",
               GIT_COMMITTER_EMAIL="bench@example.invalid",
               GIT_AUTHOR_DATE="2026-10-09T00:00:00Z",
               GIT_COMMITTER_DATE="2026-10-09T00:00:00Z")
    return env


def fixture(root, files):
    root.mkdir()
    env = isolated_env(root)
    checkout = root / "checkout"
    checkout.mkdir()
    for name, (data, mode) in files.items():
        if mode == 2:
            continue
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode else 0o644)
    for name, (data, mode) in files.items():
        if mode == 2:
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.fsdecode(data))
    for name, (_, mode) in files.items():
        if mode == 2:
            try:
                (checkout / name).resolve().relative_to(checkout.resolve())
            except (ValueError, RuntimeError):
                raise ValueError("Archive link resolves outside fixture: " + name)
    hooks = root / "empty-hooks"
    hooks.mkdir()
    git(checkout, "-c", "init.defaultBranch=main", "init", "--quiet", env=env)
    for key, value in (("core.hooksPath", str(hooks)), ("core.autocrlf", "false"),
                       ("commit.gpgsign", "false"), ("core.filemode", "true")):
        git(checkout, "config", "--local", key, value, env=env)
    git(checkout, "add", "--force", "--all", env=env)
    git(checkout, "commit", "--quiet", "-m", "Frozen baseline", env=env)
    return checkout, env


def measured_task(root, checkout, env, variant, patch, expected):
    phases = {}
    started = time.perf_counter_ns()
    if variant == "checkout":
        working = checkout
        prepare = lambda: git(checkout, "checkout", "--quiet", "-b", "task", env=env)
    else:
        working = root / "linked"
        prepare = lambda: git(checkout, "worktree", "add", "--quiet", "-b", "task",
                              str(working), env=env)
    phases["prepare"], _ = duration(prepare)
    phases["patch"], _ = duration(lambda: git(working, "apply", "--binary", "-",
                                             env=env, data=patch))

    def tests():
        counts = []
        for name in TESTS:
            stdout, stderr = run([sys.executable, str(working / "tests" / name)],
                                 cwd=working, env=env)
            output = stdout + stderr
            match = re.search(rb"Ran (\d+) tests? in", output)
            if match is None or not re.search(rb"\nOK\s*$", output):
                raise RuntimeError("Focused tests did not report success")
            counts.append(int(match.group(1)))
        return counts

    phases["tests"], counts = duration(tests)

    def commit():
        git(working, "add", "--force", "--all", env=env)
        git(working, "commit", "--quiet", "-m", "Frozen feature", env=env)

    phases["commit"], _ = duration(commit)

    def integrate():
        if variant == "checkout":
            git(checkout, "checkout", "--quiet", "main", env=env)
        git(checkout, "merge", "--quiet", "--ff-only", "task", env=env)

    phases["integration"], _ = duration(integrate)
    phases["total"] = (time.perf_counter_ns() - started) / 1e6
    # Validate after timing so verification overhead cannot mask the Git delta.
    names = git(checkout, "ls-files", "-z", env=env).decode().split("\0")
    final = {}
    for name in filter(None, names):
        target = checkout / name
        mode = target.lstat().st_mode
        final[name] = ((os.fsencode(os.readlink(target)), 2) if stat.S_ISLNK(mode)
                       else (target.read_bytes(), int(bool(mode & 0o111))))
    digest = content_digest(final)
    if digest != expected or git(checkout, "status", "--porcelain", env=env):
        raise AssertionError("Final tracked content does not match the frozen feature")
    applied = git(checkout, "diff", "--binary", "--full-index", "--no-renames",
                  "--no-ext-diff", "--no-textconv", "HEAD^", "HEAD", env=env)
    if applied != patch:
        raise AssertionError("Applied patch differs from the exact frozen task unit")
    if git(checkout, "rev-parse", "HEAD", env=env) != git(checkout, "rev-parse", "task", env=env):
        raise AssertionError("Fixture main did not integrate the task commit")
    return {"phases_ms": phases, "focused_test_counts": counts,
            "tracked_content_sha256": digest, "patch_sha256": hashlib.sha256(applied).hexdigest(),
            "main_integrated": True}


def distribution(values):
    return {"count": len(values), "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[math.ceil(0.95 * len(values)) - 1], "samples_ms": values}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--output", type=Path,
                        default=PROJECT / ".tao/performance/worktree-latency.json")
    args = parser.parse_args()
    if args.pairs < 5:
        parser.error("At least five paired samples are required")
    source_start = time.perf_counter_ns()
    for revision in (BASE, FEATURE):
        if git(PROJECT, "rev-parse", "--verify", revision + "^{commit}").decode().strip() != revision:
            raise AssertionError("Frozen revision mismatch")
    if git(PROJECT, "rev-parse", FEATURE + "^").decode().strip() != BASE:
        raise AssertionError("Frozen feature is not the direct child of the baseline")
    baseline = archive_files(git(PROJECT, "archive", BASE))
    feature = archive_files(git(PROJECT, "archive", FEATURE))
    patch = git(PROJECT, "diff", "--binary", "--full-index", "--no-renames",
                "--no-ext-diff", "--no-textconv", BASE, FEATURE)
    source_ms = (time.perf_counter_ns() - source_start) / 1e6
    expected = content_digest(feature)
    samples = []
    with tempfile.TemporaryDirectory(prefix="tao-worktree-latency-") as temporary:
        for pair in range(args.pairs):
            order = ("checkout", "worktree") if pair % 2 == 0 else ("worktree", "checkout")
            for position, variant in enumerate(order):
                root = Path(temporary).resolve() / (str(pair) + "-" + variant)
                setup_ms, (checkout, env) = duration(lambda: fixture(root, baseline))
                result = measured_task(root, checkout, env, variant, patch, expected)
                samples.append({"pair": pair + 1, "position": position + 1, "variant": variant,
                                "common_fixture_setup_ms": setup_ms, **result})
    counts = {tuple(sample["focused_test_counts"]) for sample in samples}
    if len(counts) != 1:
        raise AssertionError("Focused test coverage varied across samples")
    summary = {}
    for variant in ("checkout", "worktree"):
        selected = [sample for sample in samples if sample["variant"] == variant]
        summary[variant] = {phase: distribution([s["phases_ms"][phase] for s in selected])
                            for phase in PHASES}
        summary[variant]["common_fixture_setup"] = distribution(
            [s["common_fixture_setup_ms"] for s in selected])
    deltas = {phase: distribution([
        next(s["phases_ms"][phase] for s in samples if s["pair"] == pair and s["variant"] == "worktree")
        - next(s["phases_ms"][phase] for s in samples if s["pair"] == pair and s["variant"] == "checkout")
        for pair in range(1, args.pairs + 1)]) for phase in PHASES}
    report = {"environment": {"python": sys.version, "git": git(PROJECT, "--version").decode().strip(),
                               "os": platform.platform(), "machine": platform.machine()},
              "base_revision": BASE, "feature_revision": FEATURE, "pairs": args.pairs,
              "corpus": {"baseline_members": len(baseline), "feature_members": len(feature),
                         "baseline_symlinks": sum(mode == 2 for _, mode in baseline.values()),
                         "feature_symlinks": sum(mode == 2 for _, mode in feature.values()),
                         "baseline_bytes": sum(len(value[0]) for value in baseline.values()),
                         "feature_bytes": sum(len(value[0]) for value in feature.values())},
              "patch_sha256": hashlib.sha256(patch).hexdigest(),
              "feature_content_sha256": expected,
              "benchmark_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
              "source_archive_and_patch_ms": source_ms,
              "conditions": "Fresh offline fixtures; alternating paired order; warm OS caches; "
                            "empty fixture hooks; isolated HOME/XDG/TMP/Git settings. "
                            "Local command latency only; excludes model/API/tool RPC/approvals, "
                            "dependency reinstall, live hooks and fixture cleanup. "
                            "Archive and fixture setup are outside the timed task; "
                            "p95 uses nearest rank; patch application replaces AI implementation.",
              "summary": summary, "paired_worktree_minus_checkout": deltas, "samples": samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": summary,
                      "paired_worktree_minus_checkout": deltas}, indent=2))


if __name__ == "__main__":
    main()
