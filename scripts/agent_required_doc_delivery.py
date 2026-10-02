"""Hand an agent the required docs it has not read, at its run's first file edit.

Owner: delivery of a run's unread required docs to the model.
Allowed imports: the standard library and agent_required_doc_reuse.
Callers/tests: `claude_pretool_gate.decide` (Claude and Codex);
`tests/test_agent_required_doc_delivery.py`.
Verification: that module, which covers delivery, skipping read or reused
docs, the once-per-run marker, the size cap and every fail-quiet path.

`start` lists a route's required docs and nothing checked that they were read.
Measured on 2026-10-02: Claude sessions on c8c Android routes opened almost
none of them, while Codex read them in full. The gate already sees each file
edit, so at the first edit of a run it compares the required list with the tool
calls in the transcript since the run started. It then passes the unread docs to
the model as context, the way the hook already passes policy notes. It never
blocks: the edit gets the verdict it would have had anyway. It runs once per
run, and a delivery that cannot be computed is skipped silently, so the hook
fails towards the behaviour it had before.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from agent_required_doc_reuse import required_doc_reuse

MARKER = "required-docs-delivered.json"
# One small core contract is ~4-6 KB; the cap keeps a delivery to a few of them.
MAX_INLINE_DOC_BYTES = 8 * 1024
MAX_DELIVERY_BYTES = 24 * 1024
_TOOL_CALL = ('"tool_use"', '"custom_tool_call"', '"function_call"')
_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.S)
_PATCH_FILE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: (\S[^\n]*)")
_TIMESTAMP = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')


def edited_paths(payload: dict) -> list[Path]:
    """Files a file-edit tool call names, in either runtime's shape."""

    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input, str):
        # A patch body can arrive as the bare tool input.
        tool_input = {"input": tool_input}
    if not isinstance(tool_input, dict):
        return []
    paths = [tool_input.get(key) for key in ("file_path", "notebook_path", "path")]
    for value in tool_input.values():
        if isinstance(value, str):
            paths.extend(_PATCH_FILE.findall(value))
    cwd = Path(str(payload.get("cwd") or "."))
    return [Path(p) if Path(p).is_absolute() else cwd / p for p in paths if isinstance(p, str) and p]


def delivery_text(payload: dict, evidence_for) -> str:
    """The unread required docs to show with this edit, or "" (also on any failure).

    `evidence_for(project)` returns this session's active run evidence for a
    project, or None; the gate passes its own resolver so binding stays exact.
    """

    try:
        evidence = _session_run(payload, evidence_for)
        if evidence is None:
            return ""
        marker = evidence.parent / MARKER
        if marker.exists():
            return ""
        preflight = json.loads(evidence.read_text(encoding="utf-8"))
        rules = Path(preflight["rules"])
        docs = list(dict.fromkeys(preflight["route"].get("required_docs") or []))
        reused = set(required_doc_reuse(evidence)["reused"])
        read = _read_since(Path(str(payload.get("transcript_path") or "")),
                           str(preflight.get("timestamp") or ""), docs)
        pending = [doc for doc in docs if doc not in reused and doc not in read]
        marker.write_text(json.dumps({"delivered": pending}), encoding="utf-8")
        return _render(rules, pending)
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _session_run(payload: dict, evidence_for) -> Path | None:
    for edited in edited_paths(payload):
        for project in (edited, *edited.parents):
            if (project / ".tao" / "run-registry.json").is_file():
                evidence = evidence_for(project)
                if evidence is not None:
                    return evidence
                break
    return None


def _read_since(transcript: Path, started: str, docs: list[str]) -> set[str]:
    """Docs a tool call named in the transcript at or after the run started."""

    if not transcript.is_file() or not started:
        return set()
    start = _parse(started)
    found: set[str] = set()
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(kind in line for kind in _TOOL_CALL):
                continue
            stamp = _TIMESTAMP.search(line)
            if stamp is None or _parse(stamp.group(1)) < start:
                continue
            found.update(doc for doc in docs if doc in line)
    return found


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _render(rules: Path, pending: list[str]) -> str:
    if not pending:
        return ""
    inline, listed, used = [], [], 0
    for doc in pending:
        try:
            text = _FRONTMATTER.sub("", (rules / doc).read_text(encoding="utf-8")).strip()
        except OSError:
            continue
        size = len(text.encode("utf-8"))
        if size <= MAX_INLINE_DOC_BYTES and used + size <= MAX_DELIVERY_BYTES:
            inline.append(f"=== {doc} ===\n{text}")
            used += size
        else:
            listed.append(f"{doc} ({size} bytes)")
    if not inline and not listed:
        return ""
    parts = ["Tao required docs not yet read in this run, delivered once before its first edit. "
             "Apply them to this change; this does not block the edit."]
    if listed:
        parts.append("Read these yourself before continuing (too large to include): " + "; ".join(listed))
    parts.extend(inline)
    return "\n\n".join(parts)
