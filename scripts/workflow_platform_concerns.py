"""Platform-specific concern-to-document routes for workflow routing."""

from __future__ import annotations

from typing import Dict, Tuple


ANDROID_EXTERNAL_SKILL_DOCS = (
    "platforms/android/skills/android-external-skill-source-coverage/SKILL.md",
    "platforms/android/skills/source-coverage/SKILL.md",
)

# The android-module-structure bundle is split into topic siblings so a route
# can select the boundary, layout, entry-contract, build, split, or review
# material it actually needs instead of the whole 46 KB card.  Naming a
# reference directly is already how `ANDROID_PERSISTENCE_DOCS` reaches
# `android-datastore.md`: `resolve_guidance_docs` rewrites only `SKILL.md`
# entrypoints and passes any other path through untouched.  The entrypoint
# stays in the module/structure lists so it keeps resolving to the slimmed
# `current-guidance.md`, which still carries the always-applicable core rules.
ANDROID_MODULE_STRUCTURE_DOC = "platforms/android/skills/android-module-structure/SKILL.md"
_ANDROID_MODULE_REFS = "platforms/android/skills/android-module-structure/references"
ANDROID_MODULE_BOUNDARY_DOC = f"{_ANDROID_MODULE_REFS}/module-boundaries.md"
ANDROID_MODULE_LAYOUT_DOC = f"{_ANDROID_MODULE_REFS}/module-layout.md"
ANDROID_MODULE_COMPOSE_ENTRY_DOC = f"{_ANDROID_MODULE_REFS}/compose-entry-contracts.md"
ANDROID_MODULE_DI_DOC = f"{_ANDROID_MODULE_REFS}/di-build-logic.md"
ANDROID_MODULE_SPLIT_DOC = f"{_ANDROID_MODULE_REFS}/split-and-migration.md"
ANDROID_MODULE_SKILL_SOURCE_DOC = f"{_ANDROID_MODULE_REFS}/skill-source-coverage.md"
ANDROID_MODULE_REVIEW_DOC = f"{_ANDROID_MODULE_REFS}/review-checklist.md"

ANDROID_COMPOSE_DOCS = (
    "platforms/android/skills/android-compose-ui/SKILL.md",
    "platforms/android/skills/android-review/SKILL.md",
    *ANDROID_EXTERNAL_SKILL_DOCS,
)
# Compose and UI work that crosses a module boundary needs the Compose-capable
# API rules and the entry-contract completion packet; `performance` does not,
# so it keeps the plain Compose set.
ANDROID_COMPOSE_BOUNDARY_DOCS = (
    *ANDROID_COMPOSE_DOCS,
    ANDROID_MODULE_COMPOSE_ENTRY_DOC,
)
ANDROID_STRUCTURE_DOCS = (
    ANDROID_MODULE_STRUCTURE_DOC,
    ANDROID_MODULE_BOUNDARY_DOC,
    ANDROID_MODULE_LAYOUT_DOC,
    ANDROID_MODULE_SPLIT_DOC,
    ANDROID_MODULE_REVIEW_DOC,
    *ANDROID_EXTERNAL_SKILL_DOCS,
)
# `dependency` covers both dependency direction between modules and Android
# dependency injection, so it takes the layout and DI pieces rather than the
# boundary-artifact and split material.
ANDROID_DEPENDENCY_DOCS = (
    ANDROID_MODULE_STRUCTURE_DOC,
    ANDROID_MODULE_LAYOUT_DOC,
    ANDROID_MODULE_DI_DOC,
    "platforms/android/skills/android-review/SKILL.md",
    *ANDROID_EXTERNAL_SKILL_DOCS,
)
ANDROID_PLATFORM_SURFACE_DOCS = (
    ANDROID_MODULE_STRUCTURE_DOC,
    "platforms/android/skills/android-review/SKILL.md",
    *ANDROID_EXTERNAL_SKILL_DOCS,
)
ANDROID_PERSISTENCE_DOCS = (
    "platforms/android/skills/android-state-data/SKILL.md",
    "platforms/android/skills/android-state-data/references/android-datastore.md",
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
WEB_SERVICE_STACK_DOCS = (
    "common/skills/web-service-rn-python/SKILL.md",
    "platforms/web/skills/web-architecture/SKILL.md",
    "platforms/web/skills/web-react-ui/SKILL.md",
    "platforms/web/skills/web-state-data/SKILL.md",
    "platforms/server/skills/server-api-implementation/SKILL.md",
    "platforms/react-native/skills/react-native-app/SKILL.md",
    "platforms/python/skills/python-web-service/SKILL.md",
)


PLATFORM_CONCERNS: Dict[Tuple[str, str], Tuple[str, ...]] = {
    ("android", "architecture"): (
        "platforms/android/skills/android-architecture/SKILL.md",
        ANDROID_MODULE_STRUCTURE_DOC,
        ANDROID_MODULE_BOUNDARY_DOC,
        ANDROID_MODULE_LAYOUT_DOC,
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "security"): (
        "platforms/android/skills/android-security/SKILL.md",
        "platforms/android/skills/android-review/SKILL.md",
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "compose"): ANDROID_COMPOSE_BOUNDARY_DOCS,
    ("android", "performance"): ANDROID_COMPOSE_DOCS,
    ("android", "api"): (
        ANDROID_MODULE_STRUCTURE_DOC,
        ANDROID_MODULE_COMPOSE_ENTRY_DOC,
        ANDROID_MODULE_BOUNDARY_DOC,
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "state"): (
        "platforms/android/skills/android-viewmodel-state/SKILL.md",
        "platforms/android/skills/android-compose-ui/SKILL.md",
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "ui"): ANDROID_COMPOSE_BOUNDARY_DOCS,
    ("android", "testing"): (
        "platforms/android/skills/android-review/SKILL.md",
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "test"): (
        "platforms/android/skills/android-review/SKILL.md",
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "skills"): (*ANDROID_EXTERNAL_SKILL_DOCS, ANDROID_MODULE_SKILL_SOURCE_DOC),
    ("android", "skill"): (*ANDROID_EXTERNAL_SKILL_DOCS, ANDROID_MODULE_SKILL_SOURCE_DOC),
    ("android", "structure"): ANDROID_STRUCTURE_DOCS,
    ("android", "module"): ANDROID_STRUCTURE_DOCS,
    ("android", "background"): ("platforms/android/skills/android-background-work/SKILL.md",),
    ("android", "cache"): ANDROID_PERSISTENCE_DOCS,
    ("android", "persistence"): ANDROID_PERSISTENCE_DOCS,
    ("android", "devtools"): ANDROID_PLATFORM_SURFACE_DOCS,
    ("android", "dependency"): ANDROID_DEPENDENCY_DOCS,
    ("android", "config"): (
        ANDROID_MODULE_STRUCTURE_DOC,
        ANDROID_MODULE_DI_DOC,
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "release"): ANDROID_PLATFORM_SURFACE_DOCS,
    ("android", "migration"): (
        ANDROID_MODULE_STRUCTURE_DOC,
        ANDROID_MODULE_SPLIT_DOC,
        "platforms/android/skills/android-review/SKILL.md",
        *ANDROID_EXTERNAL_SKILL_DOCS,
    ),
    ("android", "platform"): ANDROID_PLATFORM_SURFACE_DOCS,
    ("kmp", "security"): ("platforms/kmp/skills/kmp-security/SKILL.md",),
    ("kmp", "compose"): ("platforms/kmp/skills/kmp-compose-ui/SKILL.md",),
    ("kmp", "state"): ("platforms/kmp/skills/kmp-state-data/SKILL.md",),
    ("kmp", "ui"): ("platforms/kmp/skills/kmp-compose-ui/SKILL.md",),
    ("kmp", "structure"): ("platforms/kmp/skills/kmp-module-structure/SKILL.md",),
    ("kmp", "module"): ("platforms/kmp/skills/kmp-module-structure/SKILL.md",),
    ("kmp", "platform"): ("platforms/kmp/skills/kmp-platform-integration/SKILL.md",),
    ("kmp", "desktop"): (
        "platforms/kmp/skills/kmp-platform-integration/SKILL.md",
        "platforms/application/skills/application-command-ui/SKILL.md",
        "platforms/application/skills/application-system-integration/SKILL.md",
    ),
    ("flutter", "security"): ("platforms/flutter/skills/flutter-security/SKILL.md",),
    ("flutter", "widget"): ("platforms/flutter/skills/flutter-widget-ui/SKILL.md",),
    ("flutter", "state"): ("platforms/flutter/skills/flutter-state-data/SKILL.md",),
    ("flutter", "ui"): ("platforms/flutter/skills/flutter-widget-ui/SKILL.md",),
    ("flutter", "structure"): ("platforms/flutter/skills/flutter-project-structure/SKILL.md",),
    ("flutter", "module"): ("platforms/flutter/skills/flutter-project-structure/SKILL.md",),
    ("flutter", "platform"): ("platforms/flutter/skills/flutter-platform-integration/SKILL.md",),
    ("flutter", "channel"): ("platforms/flutter/skills/flutter-platform-integration/SKILL.md",),
    ("swift", "architecture"): ("platforms/swift/skills/swift-architecture/SKILL.md",),
    ("swift", "structure"): ("platforms/swift/skills/swift-code-structure/SKILL.md",),
    ("swift", "module"): ("platforms/swift/skills/swift-code-structure/SKILL.md",),
    ("swift", "state"): ("platforms/swift/skills/swift-architecture/SKILL.md",),
    ("swift", "ui"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("swift", "design"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("swift", "design-system"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("swift", "tokens"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("ios", "security"): ("platforms/ios/skills/ios-security/SKILL.md",),
    ("ios", "architecture"): ("platforms/ios/skills/ios-architecture/SKILL.md",),
    ("ios", "swiftui"): ("platforms/ios/skills/ios-swiftui-ui/SKILL.md", "platforms/swift/skills/swift-design-system/SKILL.md"),
    ("ios", "uikit"): ("platforms/ios/skills/ios-uikit-ui/SKILL.md", "platforms/swift/skills/swift-design-system/SKILL.md"),
    ("ios", "state"): ("platforms/ios/skills/ios-state-concurrency/SKILL.md",),
    ("ios", "ui"): ("platforms/ios/skills/ios-swiftui-ui/SKILL.md", "platforms/swift/skills/swift-design-system/SKILL.md"),
    ("ios", "design"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("ios", "design-system"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("ios", "tokens"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("ios", "structure"): ("platforms/ios/skills/ios-module-structure/SKILL.md",),
    ("ios", "module"): ("platforms/ios/skills/ios-module-structure/SKILL.md",),
    ("web", "accessibility"): ("platforms/web/skills/web-accessibility-i18n/SKILL.md",),
    ("web", "react"): ("platforms/web/skills/web-react-ui/SKILL.md",),
    ("web", "state"): ("platforms/web/skills/web-state-data/SKILL.md",),
    ("web", "api"): ("platforms/web/skills/web-state-data/SKILL.md", "platforms/web/skills/web-security/SKILL.md"),
    ("web", "cache"): ("platforms/web/skills/web-state-data/SKILL.md", "platforms/web/skills/web-security/SKILL.md"),
    ("web", "persistence"): ("platforms/web/skills/web-state-data/SKILL.md", "platforms/web/skills/web-security/SKILL.md"),
    ("web", "auth"): ("platforms/web/skills/web-state-data/SKILL.md", "platforms/web/skills/web-security/SKILL.md"),
    ("web", "ui"): ("platforms/web/skills/web-react-ui/SKILL.md", "platforms/web/skills/web-design-system/SKILL.md"),
    ("web", "component"): ("platforms/web/skills/web-react-ui/SKILL.md", "platforms/web/skills/web-design-system/SKILL.md"),
    ("web", "component-api"): ("platforms/web/skills/web-react-ui/SKILL.md", "platforms/web/skills/web-design-system/SKILL.md"),
    ("web", "structure"): ("platforms/web/skills/web-code-structure/SKILL.md",),
    ("web", "security"): ("platforms/web/skills/web-security/SKILL.md",),
    ("server", "api"): ("platforms/server/skills/server-api-implementation/SKILL.md",),
    ("react-native", "react"): REACT_NATIVE_DOCS,
    ("react-native", "ui"): REACT_NATIVE_DOCS,
    ("react-native", "component"): REACT_NATIVE_DOCS,
    ("react-native", "state"): REACT_NATIVE_DOCS,
    ("react-native", "api"): REACT_NATIVE_DOCS,
    ("react-native", "performance"): (
        *REACT_NATIVE_DOCS,
        "common/skills/performance-verification/SKILL.md",
    ),
    ("python", "api"): PYTHON_WEB_SERVICE_DOCS,
    ("python", "web-service"): PYTHON_WEB_SERVICE_DOCS,
    ("python", "python-web-service"): PYTHON_WEB_SERVICE_DOCS,
    ("python", "fastapi"): PYTHON_WEB_SERVICE_DOCS,
    ("python", "security"): (
        *PYTHON_WEB_SERVICE_DOCS,
        "platforms/server/skills/server-security/SKILL.md",
    ),
    ("web-service", "react"): WEB_SERVICE_STACK_DOCS,
    ("web-service", "react-native"): WEB_SERVICE_STACK_DOCS,
    ("web-service", "python"): WEB_SERVICE_STACK_DOCS,
    ("web-service", "api"): WEB_SERVICE_STACK_DOCS,
    ("server", "security"): ("platforms/server/skills/server-security/SKILL.md",),
    ("application", "swift"): (
        "platforms/swift/skills/swift-architecture/SKILL.md",
        "platforms/swift/skills/swift-code-structure/SKILL.md",
        "platforms/swift/skills/swift-design-system/SKILL.md",
        "platforms/swift/skills/swift-review/SKILL.md",
    ),
    ("application", "architecture"): ("platforms/application/skills/application-architecture/SKILL.md",),
    ("application", "desktop"): (
        "platforms/application/skills/application-react-desktop/SKILL.md",
        "platforms/application/skills/application-command-ui/SKILL.md",
    ),
    ("application", "react"): (
        "platforms/application/skills/application-react-desktop/SKILL.md",
        "platforms/web/skills/web-code-structure/SKILL.md",
        "platforms/web/skills/web-react-ui/SKILL.md",
        "platforms/web/skills/web-state-data/SKILL.md",
    ),
    ("application", "ui"): ("platforms/application/skills/application-command-ui/SKILL.md",),
    ("application", "design"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("application", "design-system"): ("platforms/swift/skills/swift-design-system/SKILL.md",),
    ("application", "security"): ("platforms/application/skills/application-security/SKILL.md",),
}
