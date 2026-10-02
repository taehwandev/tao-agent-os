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
edit, so at the first edit of a run it compares the required list with the
complete reads still in context (see `_read_in_context`). It then passes the unread docs to
the model as context, the way the hook already passes policy notes. It never
blocks: the edit gets the verdict it would have had anyway. It runs once per
run, and a delivery that cannot be computed is skipped silently, so the hook
fails towards the behaviour it had before.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_required_doc_reuse import required_doc_reuse

MARKER = "required-docs-delivered.json"
# One small core contract is ~4-6 KB; the cap keeps a delivery to a few of them.
MAX_INLINE_DOC_BYTES = 8 * 1024
MAX_DELIVERY_BYTES = 24 * 1024
# Cheap substring filters before a transcript line is parsed.
_TOOL_EVENT = ('"tool_use"', '"tool_result"', '"custom_tool_call', '"function_call',
               '"CommandExecution"')
# Claude's and Codex's markers for a compaction that drops earlier tool output.
_COMPACTION = ('"subtype":"compact_boundary"', '"type":"compacted"')
_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.S)
_PATCH_FILE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: (\S[^\n]*)")


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
        read = _read_in_context(Path(str(payload.get("transcript_path") or "")), rules, docs)
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


def _read_in_context(transcript: Path, rules: Path, docs: list[str]) -> set[str]:
    """Docs whose full, current text a tool result put into the live context.

    Counting a tool call that merely named a doc credited searches, failed and
    partial reads; counting only calls since the run started re-delivered docs
    read just before `start` that were still in context. A doc counts when a
    successful call naming it returned every line of the doc's current text
    (a complete read of this version, not a slice or an older one) after the
    last compaction (so the text is still there). File times are no guide: a
    fresh worktree checkout restamps every unchanged doc.
    """

    if not transcript.is_file():
        return set()
    texts = {doc: _lines(rules / doc) for doc in docs}
    texts = {doc: lines for doc, lines in texts.items() if lines}
    calls: dict[str, list[str]] = {}
    found: set[str] = set()
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if any(marker in line for marker in _COMPACTION):
                calls.clear()
                found.clear()
                continue
            if not any(kind in line for kind in _TOOL_EVENT):
                continue
            # Parse only a call naming a doc, or the result of one.
            if not any(doc in line for doc in texts) and not any(call in line for call in calls):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for call_id, named, output, failed in _tool_events(row, texts):
                if output is None:
                    calls[call_id] = named
                    continue
                named = calls.pop(call_id, named)
                if not failed:
                    found.update(doc for doc in named
                                 if all(text in output for text in texts[doc]))
    return found


def _tool_events(row: dict, texts: dict[str, list[str]]):
    """(call id, docs named, output or None for a call, failed) in either runtime's shape."""

    def named(value) -> list[str]:
        text = json.dumps(value, ensure_ascii=False)
        return [doc for doc in texts if doc in text]

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    if item.get("type") == "CommandExecution":
        # Codex reports a finished shell command with its output in one event.
        failed = item.get("status") != "completed" or item.get("exit_code") not in (None, 0)
        yield str(item.get("id")), named(item.get("command")), str(item.get("stdout") or ""), failed
        return
    kind = payload.get("type", "")
    if kind in ("function_call", "custom_tool_call"):
        yield str(payload.get("call_id")), named(payload.get("arguments") or payload.get("input")), None, False
    elif kind in ("function_call_output", "custom_tool_call_output"):
        output = payload.get("output")
        yield str(payload.get("call_id")), [], json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output, False
    content = (row.get("message") or {}).get("content") if isinstance(row.get("message"), dict) else None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            yield str(block.get("id")), named(block.get("input")), None, False
        elif block.get("type") == "tool_result":
            yield (str(block.get("tool_use_id")), [], _result_text(block.get("content")),
                   bool(block.get("is_error")))


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return ""


def _lines(path: Path) -> list[str]:
    """The doc's substantive lines, frontmatter included since a read returns it."""

    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


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
