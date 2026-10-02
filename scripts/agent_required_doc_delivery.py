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
    read just before `start` that were still in context. A doc counts when
    successful calls naming it returned exact, contiguous portions of the
    doc's current text that together cover it after the last compaction.
    Extra or reordered rules cannot prove a read of this version. File times
    are no guide: a fresh checkout restamps every unchanged doc.
    """

    if not transcript.is_file():
        return set()
    texts = {doc: _lines(rules / doc) for doc in docs}
    texts = {doc: lines for doc, lines in texts.items() if lines}
    calls: dict[str, list[str]] = {}
    covered: dict[str, set[int]] = {}
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(kind in line for kind in (*_TOOL_EVENT, '"compact_boundary"', '"compacted"')):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("type") == "compacted" or (
                row.get("type") == "system" and row.get("subtype") == "compact_boundary"
            ):
                calls.clear()
                covered.clear()
                continue
            if not any(doc in line for doc in texts) and not any(call in line for call in calls):
                continue
            for call_id, named, output, failed in _tool_events(row, texts):
                if output is None:
                    calls[call_id] = named
                    continue
                named = calls.pop(call_id, named)
                if not failed:
                    for doc, span in _read_spans(named, texts, output).items():
                        covered.setdefault(doc, set()).update(span)
    return {doc for doc, span in covered.items() if len(span) == len(texts[doc])}


def _read_spans(named: list[str], texts: dict[str, list[str]], output: str) -> dict[str, range]:
    """Credit only exact current text; ambiguous slices remain unconfirmed."""

    if output.startswith(("Chunk ID:", "Wall time:", "Process exited")):
        if re.search(r"Process exited with code [1-9]\d*", output):
            return {}
        output = re.split(r"\n(?:Final output|Output):\n", output, maxsplit=1)[-1]
    lines = [re.sub(r"^\s*\d+(?:\t|→)", "", line).strip() for line in output.splitlines()]
    lines = [line for line in lines if line]
    if not named or not lines:
        return {}
    if len(named) > 1:
        if lines == [line for doc in named for line in texts[doc]]:
            return {doc: range(len(texts[doc])) for doc in named}
        return {}
    doc = named[0]
    starts = [index for index in range(len(texts[doc]) - len(lines) + 1)
              if texts[doc][index:index + len(lines)] == lines]
    if len(starts) != 1:
        return {}
    return {doc: range(starts[0], starts[0] + len(lines))}


def _tool_events(row: dict, texts: dict[str, list[str]]):
    """(call id, docs named, output or None for a call, failed) in either runtime's shape."""

    def named(value) -> list[str]:
        text = json.dumps(value, ensure_ascii=False)
        return sorted((doc for doc in texts if doc in text), key=text.index)

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
        yield str(payload.get("call_id")), [], _result_text(payload.get("output")), False
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
        try:
            decoded = json.loads(content)
        except ValueError:
            return content
        if not isinstance(decoded, (dict, list)):
            return content
        content = decoded
    if isinstance(content, dict):
        if content.get("exit_code") not in (None, 0) or content.get("is_error") or content.get("isError"):
            return ""
        for key in ("stdout", "output", "text", "content", "result", "value"):
            if key in content:
                return _result_text(content[key])
        return ""
    if isinstance(content, list):
        return "\n".join(_result_text(part) for part in content)
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
