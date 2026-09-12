"""Concern-to-document routes for workflow routing."""

from __future__ import annotations

from typing import Dict, Tuple


PUBLIC_DISCOVERY_DOCS = ("common/skills/public-discovery/SKILL.md",)
WEB_SERVICE_STACK_DOCS = (
    "common/skills/web-service-rn-python/SKILL.md",
    "platforms/web/skills/web-architecture/SKILL.md",
    "platforms/web/skills/web-react-ui/SKILL.md",
    "platforms/web/skills/web-state-data/SKILL.md",
    "platforms/server/skills/server-api-implementation/SKILL.md",
    "platforms/react-native/skills/react-native-app/SKILL.md",
    "platforms/python/skills/python-web-service/SKILL.md",
)
REACT_NATIVE_DOCS = (
    "platforms/react-native/skills/react-native-app/SKILL.md",
    "platforms/web/skills/web-react-ui/SKILL.md",
    "platforms/web/skills/web-state-data/SKILL.md",
)
PYTHON_WEB_SERVICE_DOCS = (
    "platforms/python/skills/python-web-service/SKILL.md",
    "platforms/server/skills/server-api-implementation/SKILL.md",
)


CONCERNS: Dict[str, Tuple[str, ...]] = {
    "security": ("common/skills/secure-development-baseline/SKILL.md", "common/skills/security-privacy-review/SKILL.md"),
    "runtime-url": ("common/skills/runtime-url-configuration/SKILL.md",),
    "url": ("common/skills/runtime-url-configuration/SKILL.md",),
    "config": ("common/skills/runtime-url-configuration/SKILL.md",),
    "intake": ("common/skills/task-intake-effort-routing/SKILL.md", "workflows/skills/request-triage/SKILL.md"),
    "effort": ("common/skills/task-intake-effort-routing/SKILL.md",),
    # The testing card carries the always-applicable test rules and links the
    # other two; see CONCERN_REFERENCE_DOCS.
    "testing": ("common/skills/testing/SKILL.md",),
    "test": ("common/skills/testing/SKILL.md",),
    "verification": (
        "common/skills/verification-policy/SKILL.md",
        "common/skills/testing/SKILL.md",
        "common/skills/scenario-driven-testing/SKILL.md",
        "common/skills/definition-of-done/SKILL.md",
    ),
    "done": ("common/skills/definition-of-done/SKILL.md", "common/skills/verification-policy/SKILL.md"),
    "definition-of-done": ("common/skills/definition-of-done/SKILL.md", "common/skills/verification-policy/SKILL.md"),
    "api": ("common/skills/api-contract-compatibility/SKILL.md",),
    "web-service": WEB_SERVICE_STACK_DOCS,
    "web-service-stack": WEB_SERVICE_STACK_DOCS,
    "react-native": REACT_NATIVE_DOCS,
    "rn": REACT_NATIVE_DOCS,
    "expo": REACT_NATIVE_DOCS,
    "python": PYTHON_WEB_SERVICE_DOCS,
    "python-web-service": PYTHON_WEB_SERVICE_DOCS,
    "fastapi": PYTHON_WEB_SERVICE_DOCS,
    "architecture": ("common/skills/architecture-selection/SKILL.md", "common/skills/architecture-design/SKILL.md", "common/skills/app-architecture/SKILL.md"),
    "swift": (
        "platforms/swift/skills/swift-architecture/SKILL.md",
        "platforms/swift/skills/swift-code-structure/SKILL.md",
        "platforms/swift/skills/swift-design-system/SKILL.md",
        "platforms/swift/skills/swift-review/SKILL.md",
    ),
    "asset": ("common/skills/asset-lifecycle/SKILL.md",),
    "assets": ("common/skills/asset-lifecycle/SKILL.md",),
    "structure": ("common/skills/code-structure-ownership/SKILL.md",),
    "module": ("common/skills/code-structure-ownership/SKILL.md",),
    "reusability": ("common/skills/reusable-code-design/SKILL.md", "common/skills/component-api-design/SKILL.md"),
    "component": ("common/skills/component-api-design/SKILL.md",),
    "component-api": ("common/skills/component-api-design/SKILL.md",),
    "state": ("common/skills/state-modeling/SKILL.md",),
    "error": ("common/skills/error-modeling/SKILL.md",),
    "errors": ("common/skills/error-modeling/SKILL.md",),
    "ui": ("common/skills/design-system/SKILL.md", "common/skills/component-api-design/SKILL.md", "common/skills/ui-visual-verification/SKILL.md"),
    "design": ("common/skills/design-system/SKILL.md", "common/skills/component-api-design/SKILL.md", "common/skills/ui-visual-verification/SKILL.md"),
    "design-system": ("common/skills/design-system/SKILL.md", "common/skills/component-api-design/SKILL.md", "common/skills/ui-visual-verification/SKILL.md"),
    "tokens": ("common/skills/design-system/SKILL.md", "common/skills/ui-visual-verification/SKILL.md"),
    "accessibility": ("common/skills/accessibility-i18n/SKILL.md",),
    "i18n": ("common/skills/accessibility-i18n/SKILL.md",),
    "localization": ("common/skills/accessibility-i18n/SKILL.md",),
    "number-format": ("common/skills/accessibility-i18n/SKILL.md",),
    "number": ("common/skills/accessibility-i18n/SKILL.md",),
    "numbers": ("common/skills/accessibility-i18n/SKILL.md",),
    "numeric": ("common/skills/accessibility-i18n/SKILL.md",),
    "unit": ("common/skills/accessibility-i18n/SKILL.md",),
    "units": ("common/skills/accessibility-i18n/SKILL.md",),
    "measurement": ("common/skills/accessibility-i18n/SKILL.md",),
    "measurements": ("common/skills/accessibility-i18n/SKILL.md",),
    "currency": ("common/skills/accessibility-i18n/SKILL.md",),
    "display-value": ("common/skills/accessibility-i18n/SKILL.md",),
    "display-values": ("common/skills/accessibility-i18n/SKILL.md",),
    "documentation": ("workflows/skills/documentation-update/SKILL.md",),
    "writing": ("common/skills/human-authored-writing/SKILL.md", "common/skills/writing-workspace/SKILL.md"),
    "prose": ("common/skills/human-authored-writing/SKILL.md", "common/skills/writing-workspace/SKILL.md"),
    "voice": ("common/skills/human-authored-writing/SKILL.md",),
    "copy": ("common/skills/human-authored-writing/SKILL.md", "common/skills/accessibility-i18n/SKILL.md"),
    "skill": (
        "common/skills/agent-skill-card-anatomy/SKILL.md",
        "docs/skills/tao-skill-bundle-migration/SKILL.md",
        "workflows/skills/documentation-update/SKILL.md",
    ),
    "skills": (
        "common/skills/agent-skill-card-anatomy/SKILL.md",
        "docs/skills/tao-skill-bundle-migration/SKILL.md",
        "workflows/skills/documentation-update/SKILL.md",
    ),
    "skill-card": (
        "common/skills/agent-skill-card-anatomy/SKILL.md",
        "docs/skills/tao-skill-bundle-migration/SKILL.md",
        "workflows/skills/documentation-update/SKILL.md",
    ),
    "card-anatomy": (
        "common/skills/agent-skill-card-anatomy/SKILL.md",
        "docs/skills/tao-skill-bundle-migration/SKILL.md",
        "workflows/skills/documentation-update/SKILL.md",
    ),
    "source-driven": ("common/skills/source-driven-development/SKILL.md",),
    "source": ("common/skills/source-driven-development/SKILL.md",),
    "official-docs": ("common/skills/source-driven-development/SKILL.md",),
    "doubt": ("common/skills/doubt-driven-development/SKILL.md", "workflows/skills/multi-perspective-review/SKILL.md"),
    "doubt-driven": ("common/skills/doubt-driven-development/SKILL.md", "workflows/skills/multi-perspective-review/SKILL.md"),
    "incremental": ("common/skills/incremental-implementation/SKILL.md",),
    "slice": ("common/skills/incremental-implementation/SKILL.md",),
    "slicing": ("common/skills/incremental-implementation/SKILL.md",),
    "deprecation": ("common/skills/deprecation-migration/SKILL.md", "common/skills/release-deployment/SKILL.md"),
    "migration": ("common/skills/deprecation-migration/SKILL.md", "common/skills/data-persistence-sync/SKILL.md"),
    "ci": ("common/skills/ci-cd-automation/SKILL.md",),
    "cd": ("common/skills/ci-cd-automation/SKILL.md",),
    "automation": ("common/skills/ci-cd-automation/SKILL.md",),
    "shipping": ("common/skills/ci-cd-automation/SKILL.md", "workflows/skills/release-readiness/SKILL.md", "common/skills/web-deployment-versioning/SKILL.md"),
    "commit": ("common/skills/commit-workflow/SKILL.md", "common/skills/worktree-hygiene/SKILL.md", "workflows/skills/review-and-commit/SKILL.md"),
    "branch": (
        "common/skills/branch-strategy/SKILL.md",
        "common/skills/commit-workflow/SKILL.md",
        "common/skills/worktree-hygiene/SKILL.md",
        "workflows/skills/review-and-commit/SKILL.md",
    ),
    "branching": (
        "common/skills/branch-strategy/SKILL.md",
        "common/skills/commit-workflow/SKILL.md",
        "common/skills/worktree-hygiene/SKILL.md",
        "workflows/skills/review-and-commit/SKILL.md",
    ),
    "push": ("common/skills/commit-workflow/SKILL.md", "common/skills/worktree-hygiene/SKILL.md", "common/skills/secure-development-baseline/SKILL.md"),
    "pr": (
        "common/skills/branch-strategy/SKILL.md",
        "common/skills/commit-workflow/SKILL.md",
        "common/skills/worktree-hygiene/SKILL.md",
        "workflows/skills/review-and-commit/SKILL.md",
    ),
    "pull-request": (
        "common/skills/branch-strategy/SKILL.md",
        "common/skills/commit-workflow/SKILL.md",
        "common/skills/worktree-hygiene/SKILL.md",
        "workflows/skills/review-and-commit/SKILL.md",
    ),
    "tag": (
        "common/skills/commit-workflow/SKILL.md",
        "common/skills/worktree-hygiene/SKILL.md",
        "workflows/skills/release-readiness/SKILL.md",
        "common/skills/release-deployment/SKILL.md",
        "common/skills/release-versioning/SKILL.md",
    ),
    "webperf": (
        "common/skills/performance-verification/SKILL.md",
        "common/skills/web-performance-verification/SKILL.md",
        "common/skills/browser-runtime-testing/SKILL.md",
    ),
    "performance": ("common/skills/performance-verification/SKILL.md",),
    "device-testing": ("common/skills/local-tools/references/device-mcp.md",),
    "browser-testing": ("common/skills/browser-runtime-testing/SKILL.md", "common/skills/ui-visual-verification/SKILL.md"),
    "devtools": ("common/skills/browser-runtime-testing/SKILL.md",),
    "persistence": ("common/skills/data-persistence-sync/SKILL.md",),
    "cache": ("common/skills/server-side-caching/SKILL.md",),
    "release": (
        "workflows/skills/release-readiness/SKILL.md",
        "common/skills/release-deployment/SKILL.md",
        "common/skills/release-versioning/SKILL.md",
        "common/skills/web-deployment-versioning/SKILL.md",
    ),
    "dependency": ("common/skills/dependency-policy/SKILL.md",),
    "generated": ("common/skills/generated-files-policy/SKILL.md",),
    "worktree": ("common/skills/worktree-hygiene/SKILL.md",),
    "stack": ("common/skills/stack-discovery/SKILL.md",),
    "failure": ("common/skills/tool-failure-recovery/SKILL.md",),
    "interaction": ("common/skills/agent-interaction/SKILL.md",),
    "local-tools": ("common/skills/local-tools/SKILL.md", "docs/skills/agent-runtime-integration/SKILL.md"),
    "metering": ("common/skills/local-tools/SKILL.md",),
    "telemetry": ("common/skills/local-tools/SKILL.md",),
    "usage": ("common/skills/local-tools/SKILL.md",),
    "defensive": ("common/skills/defensive-boundaries/SKILL.md",),
    "observability": ("common/skills/observability-error-handling/SKILL.md", "common/skills/error-modeling/SKILL.md"),
    "discovery": PUBLIC_DISCOVERY_DOCS,
    "seo": PUBLIC_DISCOVERY_DOCS,
    "ai-mode": PUBLIC_DISCOVERY_DOCS,
    "ai-overviews": PUBLIC_DISCOVERY_DOCS,
    "ai-search": PUBLIC_DISCOVERY_DOCS,
    "ai-search-optimization": PUBLIC_DISCOVERY_DOCS,
    "aeo": PUBLIC_DISCOVERY_DOCS,
    "answer-engine": PUBLIC_DISCOVERY_DOCS,
    "answer-engine-optimization": PUBLIC_DISCOVERY_DOCS,
    "canonical": PUBLIC_DISCOVERY_DOCS,
    "generative-ai": PUBLIC_DISCOVERY_DOCS,
    "generative-ai-search": PUBLIC_DISCOVERY_DOCS,
    "geo": PUBLIC_DISCOVERY_DOCS,
    "llms": PUBLIC_DISCOVERY_DOCS,
    "llms-txt": PUBLIC_DISCOVERY_DOCS,
    "open-graph": PUBLIC_DISCOVERY_DOCS,
    "robots": PUBLIC_DISCOVERY_DOCS,
    "sitemap": PUBLIC_DISCOVERY_DOCS,
    "structured-data": PUBLIC_DISCOVERY_DOCS,
    "wiki": ("workflows/skills/documentation-update/SKILL.md", "common/skills/llm-wiki-documentation/SKILL.md"),
    "graphify": (
        "docs/skills/graphify-project-integration/SKILL.md",
        "docs/skills/agent-bootstrap/SKILL.md",
        "common/skills/llm-wiki-documentation/SKILL.md",
        "common/skills/verification-policy/SKILL.md",
    ),
    "auth": ("product-patterns/skills/auth-rbac-permissions/SKILL.md", "product-patterns/skills/auth-rbac-implementation/SKILL.md"),
    "invite": ("product-patterns/skills/invitation-workflows/SKILL.md", "product-patterns/skills/invitation-implementation/SKILL.md"),
    "billing": (
        "product-patterns/skills/billing-entitlements/SKILL.md",
        "product-patterns/skills/billing-entitlements-implementation/SKILL.md",
    ),
    "credential-broker": ("product-patterns/skills/agent-credential-broker-ideation/SKILL.md",),
    "agent-credentials": ("product-patterns/skills/agent-credential-broker-ideation/SKILL.md",),
    "brokered-credentials": ("product-patterns/skills/agent-credential-broker-ideation/SKILL.md",),
    "capability-token": ("product-patterns/skills/agent-credential-broker-ideation/SKILL.md",),
    "egress-control": ("product-patterns/skills/agent-credential-broker-ideation/SKILL.md",),
}


# Keyword inference is not evidence, so an inferred concern routes its cards as
# references: "not a performance change" matches as readily as a performance
# change does. These concerns are the exception. Each one guards an outcome that
# cannot be taken back -- a leaked secret, a wrong permission, a wrong charge, a
# lost row, a shipped version -- so a false positive costs one or two cards while
# a miss costs the change being made without the card that says how not to break
# it. Naming the concern explicitly is still the stronger signal; this only says
# the route does not wait for it.
#
# `release` is deliberately absent. Its miss is already covered: `release` and
# `ship` require three of its four cards as their command documents, so a real
# release request reads them without the concern. Promoting it would add 24 KB
# -- the largest concern set here -- to ordinary work whenever a request says
# "changelog" or "versioning", to supply one card the release routes do not.
RISK_CONCERNS_REQUIRED_WHEN_INFERRED: frozenset[str] = frozenset(
    {
        "agent-credentials",
        "auth",
        "billing",
        "brokered-credentials",
        "capability-token",
        "credential-broker",
        "egress-control",
        "migration",
        "security",
    }
)


# Cards a concern routes as on-demand references only. A caller naming
# `testing` gets the testing card required (10 KB); the scenario and
# verification-policy references (25 KB together) stay one link away, and a
# route whose tests gate needs them still selects them through the gate tier.
CONCERN_REFERENCE_DOCS: Dict[str, Tuple[str, ...]] = {
    "testing": ("common/skills/scenario-driven-testing/SKILL.md", "common/skills/verification-policy/SKILL.md"),
    "test": ("common/skills/scenario-driven-testing/SKILL.md", "common/skills/verification-policy/SKILL.md"),
}


BASELINE_CONCERNS: Dict[str, str] = {
    "stack": "already included in every route through CORE_DOCS.",
    "failure": "already included in every route through CORE_DOCS.",
    "interaction": "already included in every route through CORE_DOCS.",
}
