"""Measure the delivery/routing/cache contract on isolated archived inputs.

Owner: reproducible document-loading measurements for the README health audit.
Allowed imports: standard library and archived delivery, reuse, routing and graph owners.
Forbidden effects: network/model calls, live cache resets and tracked-source writes.
Verification: semantic assertions here and the corresponding owner test modules.
Run manually; timing samples do not participate in unittest discovery.
"""
import argparse
import hashlib
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
N = 200


def timing(action, prepare=lambda: None):
    for _ in range(10):
        prepare()
        action()
    values = []
    for _ in range(N):
        prepare()
        started = time.perf_counter_ns()
        action()
        values.append((time.perf_counter_ns() - started) / 1e6)
    ordered = sorted(values)
    return {"median_ms": statistics.median(values),
            "p95_ms": ordered[int(.95 * (len(ordered) - 1))], "samples_ms": values}


def observe(root, action):
    reads = []
    text_read, byte_read = Path.read_text, Path.read_bytes

    def record(path, data):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            return data
        if rel.endswith(".md") or rel == "workflow-doc-surfaces.json":
            reads.append({"path": rel, "bytes": len(data.encode() if isinstance(data, str) else data)})
        return data

    def text(path, *args, **kwargs):
        return record(path, text_read(path, *args, **kwargs))

    def binary(path, *args, **kwargs):
        return record(path, byte_read(path, *args, **kwargs))

    with patch.object(Path, "read_text", text), patch.object(Path, "read_bytes", binary):
        result = action()
    return {"opens": len(reads), "bytes": sum(r["bytes"] for r in reads), "reads": reads}, result


def worker(root, delivery_docs, mode):
    sys.path.insert(0, str(root / "scripts"))
    from workflow_route import resolve_docs
    from agent_required_doc_delivery import MARKER, delivery_text
    from agent_required_doc_reuse import record_doc_takeaway
    import workflow_doc_graph_build as build
    import workflow_doc_graph_cache as cache

    def load_required():
        route = resolve_docs("small-change", None, [],
                             surface_paths=["scripts/agent_required_doc_delivery.py"], project_root=root)
        assert not route["missing"], route["missing"]
        for doc in route["required_docs"]:
            (root / doc).read_text(encoding="utf-8")
        return route["required_docs"]

    if mode == "route-once":
        started = time.perf_counter_ns()
        docs = load_required()
        return {"elapsed_ms": (time.perf_counter_ns() - started) / 1e6, "docs": docs}

    cold_io, docs = observe(root, load_required)
    out = {"selected_docs": docs, "selected_bytes": sum((root / p).stat().st_size for p in docs),
           "route_then_read_cold_io": cold_io, "route_then_read_warm_time": timing(load_required)}
    out["route_then_read_warm_io"] = observe(root, load_required)[0]
    out["delivery"] = {}
    content = {p: (root / p).read_text(encoding="utf-8") for p in delivery_docs}
    snapshots = [{"path": p, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                  "size_bytes": len(text.encode())} for p, text in content.items()]
    for case in ("unread", "proven_reuse", "already_delivered", "read_in_context"):
        project = root / ".tao" / case
        evidence = project / ".tao" / "runs" / ("b" * 32) / "preflight.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        common = {"project": str(project), "rules": str(root),
                  "runtime_session": {"runtime": "codex", "session_id": "benchmark-only"},
                  "execution_snapshot": {"required_docs": snapshots}}
        evidence.write_text(json.dumps({**common, "agent_run_id": "b" * 32,
                                      "route": {"required_docs": delivery_docs}}))
        records = []
        if case == "proven_reuse":
            prior = evidence.parent.parent / ("a" * 32) / "preflight.json"
            prior.parent.mkdir()
            prior.write_text(json.dumps({**common, "agent_run_id": "a" * 32}))
            record_doc_takeaway(prior, "benchmark applied every required document")
            records = [{"run_id": "a" * 32, "state": "completed", "evidence_name": "preflight.json"}]
        (project / ".tao" / "run-registry.json").write_text(json.dumps({"schema_version": 1, "runs": records}))
        transcript = project / "transcript.jsonl"
        rows = []
        if case == "read_in_context":
            for p, text in content.items():
                rows.append({"type": "event_msg", "timestamp": "2099-01-01T00:00:00Z",
                             "payload": {"item": {"type": "CommandExecution", "id": p,
                             "status": "completed", "exit_code": 0, "command": "cat " + str(root / p),
                             "stdout": text}}})
        transcript.write_text("\n".join(json.dumps(r) for r in rows))
        payload = {"cwd": str(project), "tool_input": {"file_path": str(project / "fixture.py")},
                   "transcript_path": str(transcript)}
        action = lambda: delivery_text(payload, lambda candidate: evidence if candidate == project else None)
        marker = evidence.parent / MARKER
        prepare = (lambda: None) if case == "already_delivered" else lambda: marker.unlink(missing_ok=True)
        if case == "already_delivered":
            action()
        prepare()
        counted, result = observe(root, action)
        if case == "unread":
            assert result and "Tao required docs" in result
        else:
            assert result == "", (case, result)
        out["delivery"][case] = {"io": counted, "time": timing(action, prepare)}

    if mode == "current":
        docs_set = build._markdown_docs(root)
        assert len(docs_set) > 300, len(docs_set)
        paths = [root / p for p in [*sorted(docs_set), cache.RULES_FILE]]
        cache._builder_digest()

        def strict_content_key():
            digest = hashlib.sha256(cache._builder_digest().encode())
            for path in paths:
                digest.update(str(path.relative_to(root)).encode())
                try:
                    digest.update(path.read_bytes())
                except FileNotFoundError:
                    digest.update(b"absent")
            return digest.hexdigest()

        metadata = lambda: cache.document_key(root, docs_set)
        out["cache_keys"] = {"corpus_docs": len(docs_set),
                              "metadata": {"io": observe(root, metadata)[0], "time": timing(metadata)},
                              "full_content_hash": {"io": observe(root, strict_content_key)[0],
                                                    "time": timing(strict_content_key)}}
        build.build_doc_graph(root)
        build.clear_doc_graph_cache()
        persisted = build.build_doc_graph(root)
        uncached = build._graph_for(root, docs_set)
        assert persisted == uncached, "Persisted graph differs from source rebuild"
        out["source_rebuild_comparison"] = {
            "equal": True, "nodes": len(uncached),
            "edges": sum(len(edges) for edges in uncached.values())}
        fixture = root / ".tao" / "frozen_metadata"
        fixture.mkdir()
        (fixture / ".tao").mkdir()
        for name in ("alpha", "omega"):
            (fixture / (name + ".md")).write_text("# " + name)
        document = fixture / "guide.md"
        document.write_text("[x](alpha.md)\n")
        first = build.build_doc_graph(fixture)
        before = document.stat()
        original_stat = Path.stat
        before_hash = hashlib.sha256(document.read_bytes()).hexdigest()
        document.write_text("[x](omega.md)\n")
        os.utime(document, ns=(before.st_atime_ns, before.st_mtime_ns))
        after_hash = hashlib.sha256(document.read_bytes()).hexdigest()
        build.clear_doc_graph_cache()

        def frozen_stat(path, *args, **kwargs):
            return before if path == document else original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", frozen_stat):
            stale = build.build_doc_graph(fixture)
            forced = build._graph_for(fixture, build._markdown_docs(fixture))
        build.clear_doc_graph_cache()
        fresh = build.build_doc_graph(fixture)
        targets = lambda graph: sorted({edge["target"] for edge in graph["guide.md"]})
        assert targets(first) == targets(stale) == ["alpha.md"], (targets(first), targets(stale))
        assert targets(fresh) == targets(forced) == ["omega.md"] and before_hash != after_hash
        out["f03_frozen_metadata"] = {"synthetic_stat_override": True, "stale": targets(stale),
                                     "normal_metadata": targets(fresh), "content_hash_detects_change": True,
                                     "uncached_graph_detects_change": targets(forced) == ["omega.md"]}
    return out


def child(root, docs, mode):
    started = time.perf_counter_ns()
    result = subprocess.run([sys.executable, str(SCRIPT), "worker", str(root), json.dumps(docs), mode],
                            check=True, stdout=subprocess.PIPE, text=True)
    value = json.loads(result.stdout)
    value["process_wall_ms"] = (time.perf_counter_ns() - started) / 1e6
    return value


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        print(json.dumps(worker(Path(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4])))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--revision", default="HEAD", help="Document corpus commit (default: HEAD)")
        args = parser.parse_args()
        revision = subprocess.run(["git", "-C", str(PROJECT), "rev-parse", "--verify",
                                   args.revision + "^{commit}"], check=True,
                                  stdout=subprocess.PIPE, text=True).stdout.strip()
        archive = subprocess.run(["git", "-C", str(PROJECT), "archive", revision],
                                 check=True, stdout=subprocess.PIPE).stdout
        with tempfile.TemporaryDirectory(prefix="tao-health-bench-") as tmp:
            roots = {name: Path(tmp).resolve() / name for name in ("before", "current")}
            for name, root in roots.items():
                root.mkdir()
                with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                    assert all(not Path(m.name).is_absolute() and ".." not in Path(m.name).parts for m in tar)
                    tar.extractall(root)
                (root / ".tao").mkdir(exist_ok=True)
            for path in ("scripts/agent_required_doc_delivery.py", "workflow-doc-surfaces.json"):
                old = subprocess.run(["git", "-C", str(PROJECT), "show", "180bb39:" + path],
                                     check=True, stdout=subprocess.PIPE).stdout
                (roots["before"] / path).write_bytes(old)
            selected = child(roots["current"], [], "route-once")["docs"]
            data = {"environment": {"python": sys.version, "platform": platform.platform(),
                                    "machine": platform.machine(), "warm_samples": N,
                                    "fresh_process_samples": 20}, "corpus_revision": revision,
                    "baseline_implementation": "180bb39", "delivery_docs": selected,
                    "conditions": "Identical current corpus; only baseline delivery and surface rules restored; warm OS caches; instrumentation separate from timing; no model/tool transport."}
            for name, root in roots.items():
                data[name] = child(root, selected, name)
                data[name]["fresh_process_route"] = []
            for _ in range(20):
                for name, root in roots.items():
                    data[name]["fresh_process_route"].append(child(root, selected, "route-once"))
            count = len(selected)
            assert data["before"]["delivery"]["unread"]["io"]["opens"] == 2 * count
            assert data["current"]["delivery"]["unread"]["io"]["opens"] == count
            assert data["before"]["delivery"]["proven_reuse"]["io"]["opens"] == count
            assert data["current"]["delivery"]["proven_reuse"]["io"]["opens"] == 0
            assert len(data["before"]["selected_docs"]) == len(data["current"]["selected_docs"]) + 1
            data["benchmark_sha256"] = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
            target = PROJECT / ".tao" / "performance" / "health-measurements.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, indent=2))
            for name in roots:
                result = data[name]
                print(name, "selection", len(result["selected_docs"]), result["selected_bytes"],
                      "warm route+read", result["route_then_read_warm_time"]["median_ms"],
                      "observed", result["route_then_read_warm_io"]["opens"], result["route_then_read_warm_io"]["bytes"])
                for case, sample in result["delivery"].items():
                    print(name, case, sample["io"]["opens"], sample["io"]["bytes"], sample["time"]["median_ms"])
            print("raw_results", str(target))
