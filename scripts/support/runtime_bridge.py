"""User-level runtime bridge helpers for Tao Agent OS setup."""

from __future__ import annotations

import re
from pathlib import Path

RUNTIME_BRIDGE_BEGIN = "<!-- tao-runtime-bridge:start -->"
RUNTIME_BRIDGE_END = "<!-- tao-runtime-bridge:end -->"
LEGACY_RUNTIME_BRIDGE_BEGIN = "<!-- BEGIN MANAGED RUNTIME BRIDGE -->"
LEGACY_RUNTIME_BRIDGE_END = "<!-- END MANAGED RUNTIME BRIDGE -->"
# A managed block is identified by its marker, so renaming the marker orphans
# every block written under the old one: setup stops recognizing it and appends
# a second block beside it. Match the marker shape rather than a list of past
# names, so a block from any earlier naming is removed without this file having
# to carry that naming forward.
SUPERSEDED_RUNTIME_BRIDGE_PATTERN = re.compile(
    r"<!-- (?P<name>[a-z0-9-]+)-runtime-bridge:start -->[\s\S]*?"
    r"<!-- (?P=name)-runtime-bridge:end -->\n?",
    re.MULTILINE,
)
CODEX_DISPATCH_BRIDGE_PHRASE = (
    "For a bounded Codex leaf, use workflow.py dispatch --execute only when isolation is explicitly "
    "required. A matching parent profile or unavailable parent profile information both stay in the "
    "current process or use a native worker; neither condition starts a fresh Codex process."
)
RUNTIME_NATIVE_DELEGATION_PHRASES = {
    "Codex": (
        "For an eligible split, use Codex native subagents or parallel workers; the parent owns "
        "the shared contract, write scopes, integration, and final verification."
    ),
    "Claude": (
        "For an eligible split, dispatch all independent Claude Agent/Task workers before waiting; "
        "the parent owns the shared contract, integration, and final verification."
    ),
    "Antigravity": (
        "For an eligible split, use the available Gemini/AGY Antigravity parallel agent runner; "
        "the parent owns the shared contract, integration, and final verification."
    ),
}
AUTO_DELEGATION_BRIDGE_PHRASE = (
    "After routing, preflight, and required-doc reading, inspect parallel_execution and the "
    "multi-agent collaboration skill. When the runtime exposes workers and at least two meaningful "
    "slices have disjoint scopes, a stable contract, an integration owner, and focused verification, "
    "delegate automatically without waiting for explicit user multi-agent wording; otherwise record "
    "the concrete serial reason."
)
RUNTIME_START_BRIDGE_PHRASE = (
    "For multi-step work, run Tao Agent OS agent-hook.py start once; do not separately repeat "
    "workflow list, classify, route, or preflight. Always pass --request with the real user request. "
    "A work route additionally requires --intent-envelope and --runtime-session-id: build the "
    "envelope from the full conversation, bind it to the exact request fingerprint and the current "
    "opaque session id, and declare intent, bounded target, requested effects, prohibited effects, "
    "and ambiguity. When the effective effect is git_write or higher, also pass a separately recorded "
    "--approval-record bound to the same request, target, effect ceiling, and route; the envelope cannot "
    "approve itself. Without an envelope use only triage or ambiguity, and answer direct questions in "
    "the conversation. For a terse follow-up keep --request equal to the user's current words and "
    "pass prior target context through --continuation-scope, which is context only and cannot open a "
    "work route or authorize a mutation. Add --request-classified with --classification-evidence only "
    "as a delegated worker whose parent left a ready and valid execution capsule bound to the same "
    "exact request and workflow command; that flag never replaces the envelope."
)
RUNTIME_FINISH_BRIDGE_PHRASE = (
    "For multi-step work, run Tao Agent OS agent-hook.py finish before final report, commit, "
    "release, or handoff; direct agent-finish-check.py is a lower-level fallback only."
)
RUNTIME_CONTINUATION_BRIDGE_PHRASE = (
    "When the active run has continuation support, write one bounded semantic checkpoint through "
    "agent-hook.py checkpoint after required-doc reading and task scoping, then refresh it at "
    "material decisions and lifecycle transitions. Use --work-stdin for work summaries; never put "
    "prompts, transcripts, logs, command text, or secrets in the packet."
)
RUNTIME_CAPSULE_BRIDGE_PHRASES = [
    (
        "At each parent-to-worker boundary, run Tao Agent OS agent-hook.py handoff; it lazily creates "
        "the provider-neutral, content-free execution capsule for that worker and validates it once."
    ),
    (
        "Only a ready and valid handoff lets a worker reuse the parent's route, preflight, and "
        "required-doc manifest and brief, skipping duplicate startup, required-doc reading, VibeGuard, "
        "review, and finish work; the parent performs the final integration review and finish once."
    ),
    (
        "An invalid handoff is a successful fallback decision that requires the worker's normal "
        "lifecycle; never reuse mismatched capsule state."
    ),
    (
        "When handoff issues a fallback worker evidence path and opaque reservation token, pass "
        "both to dispatch or the native worker's start hook; the token is single-use, binds that "
        "pre-reserved path, and must never be replaced by an unverified existing directory."
    ),
    (
        "The parent is the sole gate-ledger owner; workers use worker-specific evidence paths, "
        "return scoped evidence, and never overwrite the parent ledger, including after an invalid "
        "handoff fallback."
    ),
]

RUNTIME_BRIDGE_GRAPH_PHRASES = [
    "Use the route/search output from that start hook for the user's current request; route/search owns natural-language document discovery.",
    "Do not wait for the user to name document keywords; infer the work surface from the request, platform, concern, and touched files, then read the route required_docs before editing or reviewing.",
    "Use workflow-doc-surfaces.json and the local document graph as routing/search inputs; treat graph neighbors as reference_docs unless the route marks them as required_docs.",
    "If routing/search misses a clearly relevant platform, concern, or document surface, stop and report the gap instead of proceeding from memory.",
]

RUNTIME_BRIDGE_COMMON_REQUIRED_PHRASES = [
    "Start every task by identifying the current project root.",
    "If the runtime starts outside the target repo or the target repo is not explicit, run Tao Agent OS agent-entry.py or project-discover.py before project work.",
    "If project discovery returns ambiguous or not_found, ask the user for the target project before routing, editing, testing, committing, or reporting completion.",
    "Before project work, open the project-root instruction file for the active runtime.",
    RUNTIME_START_BRIDGE_PHRASE,
    *RUNTIME_BRIDGE_GRAPH_PHRASES,
    *RUNTIME_CAPSULE_BRIDGE_PHRASES,
    RUNTIME_FINISH_BRIDGE_PHRASE,
    RUNTIME_CONTINUATION_BRIDGE_PHRASE,
    AUTO_DELEGATION_BRIDGE_PHRASE,
    "Do not mention Tao Agent OS setup, hook, permission, helper, or label commands in normal conversation.",
    "Do not report whether background labels, hooks, or metering ran unless the user explicitly asks about that subsystem.",
]


def runtime_bridge_required_phrases(runtime_name: str, instruction_file: str) -> list[str]:
    phrases = [
        f"{runtime_name} reads {instruction_file}.",
        *RUNTIME_BRIDGE_COMMON_REQUIRED_PHRASES,
        f"If this bridge or the project-root {instruction_file} cannot be confirmed before project work, stop before routing, editing, testing, committing, or reporting completion and ask for bridge repair.",
    ]
    native_delegation = RUNTIME_NATIVE_DELEGATION_PHRASES.get(runtime_name)
    if native_delegation:
        phrases.append(native_delegation)
    if runtime_name == "Codex":
        phrases.append(CODEX_DISPATCH_BRIDGE_PHRASE)
    return phrases


def runtime_bridge_block(root: Path, runtime_name: str, instruction_file: str) -> str:
    native_delegation = RUNTIME_NATIVE_DELEGATION_PHRASES.get(runtime_name)
    native_delegation_phrase = [f"- {native_delegation}"] if native_delegation else []
    dispatch_phrase = [f"- {CODEX_DISPATCH_BRIDGE_PHRASE}"] if runtime_name == "Codex" else []
    return "\n".join([
        RUNTIME_BRIDGE_BEGIN,
        "## Tao Agent OS Runtime Bridge",
        "",
        f"Apply this bridge before project work in {runtime_name} sessions.",
        "",
        f"- Shared Tao Agent OS root: `{root}`",
        "- Start every task by identifying the current project root.",
        "- If the runtime starts outside the target repo or the target repo is not explicit, run Tao Agent OS agent-entry.py or project-discover.py before project work.",
        "- If project discovery returns ambiguous or not_found, ask the user for the target project before routing, editing, testing, committing, or reporting completion.",
        "- Before project work, open the project-root instruction file for the active runtime.",
        f"- {runtime_name} reads {instruction_file}.",
        "- Read project-root instructions before Tao Agent OS shared guidance.",
        f"- {RUNTIME_START_BRIDGE_PHRASE}",
        "- Use the route/search output from that start hook for the user's current request; route/search owns natural-language document discovery.",
        "- Do not wait for the user to name document keywords; infer the work surface from the request, platform, concern, and touched files, then read the route required_docs before editing or reviewing.",
        "- Use workflow-doc-surfaces.json and the local document graph as routing/search inputs; treat graph neighbors as reference_docs unless the route marks them as required_docs.",
        "- If routing/search misses a clearly relevant platform, concern, or document surface, stop and report the gap instead of proceeding from memory.",
        *[f"- {phrase}" for phrase in RUNTIME_CAPSULE_BRIDGE_PHRASES],
        f"- {RUNTIME_FINISH_BRIDGE_PHRASE}",
        f"- {RUNTIME_CONTINUATION_BRIDGE_PHRASE}",
        f"- {AUTO_DELEGATION_BRIDGE_PHRASE}",
        *native_delegation_phrase,
        *dispatch_phrase,
        f"- If this bridge or the project-root {instruction_file} cannot be confirmed before project work, stop before routing, editing, testing, committing, or reporting completion and ask for bridge repair.",
        "- Do not mention Tao Agent OS setup, hook, permission, helper, or label commands in normal conversation.",
        "- Do not report whether background labels, hooks, or metering ran unless the user explicitly asks about that subsystem.",
        "- If a response exposed those background details, do not answer with an apology-only message; continue by repairing the action path or stopping with the specific blocker.",
        RUNTIME_BRIDGE_END,
        "",
    ])


def merge_runtime_bridge(
    target: Path,
    dry_run: bool,
    *,
    block: str,
    required_phrases: list[str],
) -> str:
    text = target.read_text() if target.exists() else ""
    legacy_pattern = re.compile(
        re.escape(LEGACY_RUNTIME_BRIDGE_BEGIN)
        + r"[\s\S]*?"
        + re.escape(LEGACY_RUNTIME_BRIDGE_END)
        + r"\n?",
        re.MULTILINE,
    )
    legacy_present = bool(legacy_pattern.search(text))
    if legacy_present:
        text = legacy_pattern.sub("", text)

    def _drop_superseded(match: re.Match[str]) -> str:
        # Keep the block that matches the marker in use; drop the rest.
        return match.group(0) if match.group(0).startswith(RUNTIME_BRIDGE_BEGIN) else ""

    superseded_text = SUPERSEDED_RUNTIME_BRIDGE_PATTERN.sub(_drop_superseded, text)
    superseded_present = superseded_text != text
    if superseded_present:
        text = superseded_text
    legacy_present = legacy_present or superseded_present
    pattern = re.compile(
        re.escape(RUNTIME_BRIDGE_BEGIN)
        + r"[\s\S]*?"
        + re.escape(RUNTIME_BRIDGE_END)
        + r"\n?",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if match:
        if match.group(0) == block and not legacy_present:
            return "ok"
        if dry_run:
            return "missing"
        updated = text if match.group(0) == block else pattern.sub(block, text)
    else:
        missing = [phrase for phrase in required_phrases if phrase not in text]
        if not missing:
            return "ok"
        if dry_run:
            return "missing"
        separator = "" if not text or text.endswith("\n") else "\n"
        updated = f"{text}{separator}{block}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated)
    return "installed"
