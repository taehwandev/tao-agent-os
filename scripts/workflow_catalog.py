"""Static route and platform catalogs for workflow.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from workflow_concern_docs import BASELINE_CONCERNS, CONCERNS, PUBLIC_DISCOVERY_DOCS
from workflow_concern_hints import REQUEST_CONCERN_HINTS
from workflow_platform_concerns import PLATFORM_CONCERNS


@dataclass(frozen=True)
class Profile:
    docs: Tuple[str, ...]
    gates: Tuple[str, ...]
    notes: Tuple[str, ...] = ()


CORE_DOCS = (
    "AGENTS.md",
    "index.md",
    "common/skills/agent-operating-skill/SKILL.md",
    "common/skills/stack-discovery/SKILL.md",
    "common/skills/llm-coding-discipline/SKILL.md",
    "common/skills/code-conventions/SKILL.md",
    "common/skills/tool-failure-recovery/SKILL.md",
    "common/skills/agent-interaction/SKILL.md",
    "common/skills/agent-editing-safety/SKILL.md",
)


COMMANDS: Dict[str, Profile] = {
    "triage": Profile(
        docs=(
            "workflows/skills/request-triage/SKILL.md",
            "common/skills/task-intake-effort-routing/SKILL.md",
            "workflows/skills/ambiguity-gate/SKILL.md",
        ),
        gates=("classify request", "select effort", "grill-me if needed", "route recommendation"),
        notes=("Use before loading broad context when request clarity or effort level is uncertain.",),
    ),
    "task": Profile(
        docs=("workflows/skills/agent-task-lifecycle/SKILL.md",),
        gates=("orient", "scope", "act", "verify", "report"),
        notes=("Use for general multi-step agent work.",),
    ),
    "analysis": Profile(
        docs=(),
        gates=("investigate", "report"),
        notes=(
            "Use for a bounded, read-only investigation with no code, test, durable documentation, or review output.",
        ),
    ),
    "workflow-setup": Profile(
        docs=("workflows/skills/agent-task-lifecycle/SKILL.md", "common/skills/tool-failure-recovery/SKILL.md"),
        gates=("orient", "install or repair", "runtime label handoff", "verify", "handoff"),
        notes=(
            "Use when the task changes local agent prompts, runtime hooks, "
            "workflow label bridges, or metering setup.",
        ),
    ),
    "product": Profile(
        docs=(
            "workflows/skills/scripted-agent-workflow/SKILL.md",
            "workflows/skills/ambiguity-gate/SKILL.md",
            "workflows/skills/product-architecture-delivery/SKILL.md",
            "workflows/skills/multi-perspective-review/SKILL.md",
            "workflows/skills/development-cycle/SKILL.md",
            "common/skills/product-spec-to-implementation/SKILL.md",
            "common/skills/architecture-selection/SKILL.md",
            "common/skills/architecture-design/SKILL.md",
        ),
        gates=(
            "platform selection",
            "PRD",
            "ARD",
            "pre-code review",
            "code work",
            "review",
            "tests",
            "UI tests when applicable",
            "commit readiness",
        ),
        notes=("Use when product intent must become architecture and code.",),
    ),
    "prd": Profile(
        docs=(
            "workflows/skills/ambiguity-gate/SKILL.md",
            "workflows/skills/prd-creation/SKILL.md",
            "common/skills/product-spec-to-implementation/SKILL.md",
        ),
        gates=(
            "local product docs",
            "ambiguity check",
            "PRD draft",
            "acceptance criteria",
            "open decisions",
            "handoff",
        ),
        notes=("Use when the deliverable is a PRD or product requirements note before ARD or code.",),
    ),
    "spec": Profile(
        docs=(
            "workflows/skills/ambiguity-gate/SKILL.md",
            "workflows/skills/prd-creation/SKILL.md",
            "common/skills/product-spec-to-implementation/SKILL.md",
        ),
        gates=(
            "local product docs",
            "ambiguity check",
            "PRD draft",
            "acceptance criteria",
            "open decisions",
            "handoff",
        ),
        notes=("Lifecycle alias for PRD/specification work; keep `prd` as the canonical route.",),
    ),
    "plan": Profile(
        docs=("workflows/skills/planning-research/SKILL.md", "common/skills/doubt-driven-development/SKILL.md"),
        gates=("question", "sources", "options", "recommendation"),
        notes=("Lifecycle alias for planning and research before implementation.",),
    ),
    "build": Profile(
        docs=(
            "workflows/skills/feature-implementation/SKILL.md",
            "workflows/skills/product-architecture-delivery/SKILL.md",
            "workflows/skills/development-cycle/SKILL.md",
            "common/skills/product-spec-to-implementation/SKILL.md",
            "common/skills/incremental-implementation/SKILL.md",
            "common/skills/source-driven-development/SKILL.md",
            "common/skills/doubt-driven-development/SKILL.md",
        ),
        gates=("PRD/ARD applicability", "acceptance criteria", "implementation", "verification", "handoff"),
        notes=("Lifecycle alias for a scoped build slice; use `product` for broad product delivery.",),
    ),
    "test": Profile(
        docs=(
            "common/skills/testing/SKILL.md",
            "common/skills/scenario-driven-testing/SKILL.md",
            "common/skills/verification-policy/SKILL.md",
            "common/skills/browser-runtime-testing/SKILL.md",
        ),
        gates=("test scope", "run checks", "evidence", "handoff"),
        notes=("Lifecycle alias for verification-only work or test evidence collection.",),
    ),
    "webperf": Profile(
        docs=(
            "common/skills/performance-verification/SKILL.md",
            "common/skills/web-performance-verification/SKILL.md",
            "common/skills/browser-runtime-testing/SKILL.md",
            "common/skills/ui-visual-verification/SKILL.md",
        ),
        gates=("baseline", "measure", "risk review", "recommendation", "handoff"),
        notes=("Lifecycle alias for browser and web performance review.",),
    ),
    "code-simplify": Profile(
        docs=(
            "workflows/skills/refactor-cleanup/SKILL.md",
            "common/skills/refactoring/SKILL.md",
            "common/skills/incremental-implementation/SKILL.md",
            "common/skills/code-structure-ownership/SKILL.md",
        ),
        gates=("behavior baseline", "simplification plan", "small refactor", "equivalence check", "handoff"),
        notes=("Lifecycle alias for behavior-preserving simplification.",),
    ),
    "ambiguity": Profile(
        docs=("workflows/skills/ambiguity-gate/SKILL.md", "common/skills/product-spec-to-implementation/SKILL.md"),
        gates=("classify unknowns", "research repo-answerable items", "ask blockers", "record assumptions"),
        notes=("Use before PRD, ARD, task breakdown, or implementation when unknowns can change behavior or risk.",),
    ),
    "feature": Profile(
        docs=(
            "workflows/skills/feature-implementation/SKILL.md",
            "workflows/skills/product-architecture-delivery/SKILL.md",
            "workflows/skills/development-cycle/SKILL.md",
            "common/skills/product-spec-to-implementation/SKILL.md",
        ),
        gates=("PRD/ARD applicability", "acceptance criteria", "implementation", "verification", "handoff"),
    ),
    "bugfix": Profile(
        docs=("workflows/skills/bugfix-debugging/SKILL.md", "workflows/skills/development-cycle/SKILL.md"),
        gates=("reproduce", "isolate", "fix", "regression check", "handoff"),
    ),
    "refactor": Profile(
        docs=("workflows/skills/refactor-cleanup/SKILL.md", "common/skills/refactoring/SKILL.md"),
        gates=("behavior baseline", "small refactor", "equivalence check", "handoff"),
    ),
    "docs": Profile(
        docs=("workflows/skills/documentation-update/SKILL.md",),
        gates=("source of truth", "edit", "link/path check", "handoff"),
    ),
    "docs-review": Profile(
        docs=(
            "workflows/skills/review-and-commit/SKILL.md",
            "workflows/skills/documentation-update/SKILL.md",
            "workflows/skills/multi-perspective-review/SKILL.md",
            "common/skills/code-review/SKILL.md",
            "common/skills/llm-wiki-documentation/SKILL.md",
        ),
        gates=(
            "review readiness",
            "source review",
            "structure review",
            "link/path check",
            "verification",
            "handoff",
        ),
        notes=("Use for reviewing durable docs, wiki pages, operational guides, and runbooks.",),
    ),
    "commit": Profile(
        docs=(
            "workflows/skills/review-and-commit/SKILL.md",
            "common/skills/commit-workflow/SKILL.md",
            "common/skills/code-review/SKILL.md",
            "common/skills/worktree-hygiene/SKILL.md",
        ),
        gates=("commit readiness",),
        notes=(
            "Use for local commit preparation and for a combined commit, push, and pull-request follow-up. "
            "Run the lightweight review first; if review finds issues, stop before committing and report required fixes. "
            "Use release only when the request actually packages, deploys, tags, migrates, or publishes a release artifact.",
        ),
    ),
    "planning": Profile(
        docs=("workflows/skills/planning-research/SKILL.md",),
        gates=("question", "sources", "options", "recommendation"),
    ),
    "review": Profile(
        docs=(
            "workflows/skills/review-and-commit/SKILL.md",
            "workflows/skills/multi-perspective-review/SKILL.md",
            "common/skills/code-review/SKILL.md",
        ),
        gates=("diff review", "risk review", "verification", "commit readiness"),
    ),
    "multi-agent": Profile(
        docs=("workflows/skills/multi-agent-collaboration/SKILL.md", "workflows/skills/agent-handoff-continuation/SKILL.md"),
        gates=("roles", "write scopes", "agent briefs", "integration review", "handoff"),
        notes=("Use when work is delegated, parallelized, or split into builder/verifier roles.",),
    ),
    "release": Profile(
        docs=(
            "workflows/skills/release-readiness/SKILL.md",
            "common/skills/release-deployment/SKILL.md",
            "common/skills/release-versioning/SKILL.md",
            "common/skills/ci-cd-automation/SKILL.md",
            "common/skills/deprecation-migration/SKILL.md",
        ),
        gates=("package", "config", "smoke", "rollback", "handoff"),
    ),
    "ship": Profile(
        docs=(
            "workflows/skills/release-readiness/SKILL.md",
            "common/skills/release-deployment/SKILL.md",
            "common/skills/release-versioning/SKILL.md",
            "common/skills/ci-cd-automation/SKILL.md",
            "common/skills/deprecation-migration/SKILL.md",
        ),
        gates=("package", "config", "smoke", "rollback", "handoff"),
        notes=("Lifecycle alias for release and shipping readiness; keep `release` as the canonical route.",),
    ),
    "retrospective": Profile(
        docs=("workflows/skills/retrospective-learning/SKILL.md",),
        gates=("trigger", "lesson", "promotion check", "doc update"),
    ),
}
COMMANDS["git_commit"] = COMMANDS["commit"]


SPILL_ACTION_LABELS: Dict[str, Tuple[str, str]] = {
    "classify": ("analysis", "classify"),
    "dispatch": ("workflow_setup", "plan"),
    "dispatch-finalize": ("workflow_setup", "implement"),
    "list": ("analysis", "classify"),
    "query": ("analysis", "classify"),
    "validate": ("build_verification", "verify"),
}


SPILL_ROUTE_LABELS: Dict[str, Tuple[str, str]] = {
    "analysis": ("analysis", "summarize"),
    "ambiguity": ("analysis", "classify"),
    "bugfix": ("debugging", "implement"),
    "docs": ("documentation", "draft"),
    "docs-review": ("code_review", "verify"),
    "feature": ("code_generation", "implement"),
    "build": ("code_generation", "implement"),
    "commit": ("git_commit", "verify"),
    "git_commit": ("git_commit", "verify"),
    "multi-agent": ("architecture", "plan"),
    "plan": ("analysis", "plan"),
    "planning": ("analysis", "plan"),
    "prd": ("prd_drafting", "draft"),
    "spec": ("prd_drafting", "draft"),
    "product": ("architecture", "plan"),
    "refactor": ("refactoring", "implement"),
    "code-simplify": ("refactoring", "implement"),
    "release": ("release_packaging", "verify"),
    "ship": ("release_packaging", "verify"),
    "retrospective": ("documentation", "revise"),
    "review": ("code_review", "verify"),
    "task": ("analysis", "plan"),
    "test": ("testing", "verify"),
    "triage": ("analysis", "classify"),
    "webperf": ("build_verification", "verify"),
    "workflow-setup": ("workflow_setup", "implement"),
}


PLATFORMS: Dict[str, Tuple[str, ...]] = {
    "android": (
        "platforms/android/skills/android-architecture/SKILL.md",
        "platforms/android/skills/android-module-structure/SKILL.md",
        "platforms/android/skills/android-viewmodel-state/SKILL.md",
        "platforms/android/skills/android-state-data/SKILL.md",
        "platforms/android/skills/android-review/SKILL.md",
    ),
    "kmp": (
        "platforms/kmp/skills/kmp-architecture/SKILL.md",
        "platforms/kmp/skills/kmp-module-structure/SKILL.md",
        "platforms/kmp/skills/kmp-compose-ui/SKILL.md",
        "platforms/kmp/skills/kmp-state-data/SKILL.md",
        "platforms/kmp/skills/kmp-platform-integration/SKILL.md",
        "platforms/kmp/skills/kmp-review/SKILL.md",
    ),
    "flutter": (
        "platforms/flutter/skills/flutter-architecture/SKILL.md",
        "platforms/flutter/skills/flutter-project-structure/SKILL.md",
        "platforms/flutter/skills/flutter-widget-ui/SKILL.md",
        "platforms/flutter/skills/flutter-state-data/SKILL.md",
        "platforms/flutter/skills/flutter-platform-integration/SKILL.md",
        "platforms/flutter/skills/flutter-review/SKILL.md",
    ),
    "swift": (
        "platforms/swift/skills/swift-architecture/SKILL.md",
        "platforms/swift/skills/swift-code-structure/SKILL.md",
        "platforms/swift/skills/swift-design-system/SKILL.md",
        "platforms/swift/skills/swift-review/SKILL.md",
    ),
    "ios": (
        "platforms/swift/skills/swift-architecture/SKILL.md",
        "platforms/swift/skills/swift-code-structure/SKILL.md",
        "platforms/swift/skills/swift-design-system/SKILL.md",
        "platforms/swift/skills/swift-review/SKILL.md",
        "platforms/ios/skills/ios-architecture/SKILL.md",
        "platforms/ios/skills/ios-module-structure/SKILL.md",
        "platforms/ios/skills/ios-state-concurrency/SKILL.md",
        "platforms/ios/skills/ios-review/SKILL.md",
    ),
    "web": (
        "platforms/web/skills/web-architecture/SKILL.md",
        "platforms/web/skills/web-code-structure/SKILL.md",
        "platforms/web/skills/web-state-data/SKILL.md",
        "platforms/web/skills/web-review/SKILL.md",
    ),
    "react-native": (
        "platforms/react-native/skills/react-native-app/SKILL.md",
        "platforms/web/skills/web-react-ui/SKILL.md",
        "platforms/web/skills/web-state-data/SKILL.md",
    ),
    "python": (
        "platforms/server/skills/server-architecture/SKILL.md",
        "platforms/server/skills/server-api-implementation/SKILL.md",
        "platforms/python/skills/python-web-service/SKILL.md",
    ),
    "web-service": (
        "common/skills/web-service-rn-python/SKILL.md",
        "platforms/web/skills/web-architecture/SKILL.md",
        "platforms/web/skills/web-react-ui/SKILL.md",
        "platforms/web/skills/web-state-data/SKILL.md",
        "platforms/server/skills/server-api-implementation/SKILL.md",
        "platforms/react-native/skills/react-native-app/SKILL.md",
        "platforms/python/skills/python-web-service/SKILL.md",
    ),
    "server": (
        "platforms/server/skills/server-architecture/SKILL.md",
        "platforms/server/skills/server-api-implementation/SKILL.md",
        "platforms/server/skills/server-data-jobs/SKILL.md",
        "platforms/server/skills/server-review/SKILL.md",
    ),
    "application": (
        "platforms/application/skills/application-architecture/SKILL.md",
        "platforms/application/skills/application-command-ui/SKILL.md",
        "platforms/application/skills/application-system-integration/SKILL.md",
        "platforms/application/skills/application-review/SKILL.md",
    ),
}
