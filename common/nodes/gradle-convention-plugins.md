---
keyflow_id: sys_common_node_gradle_convention_plugins
status: review
type: ai-generated
use_when: adding, changing, or cleaning up Gradle convention plugins or shared build-logic in Android, KMP, or JVM builds
skip_when: the build has no included build-logic or the change touches no shared Gradle setup
---

# Gradle Convention Plugins

## Rules

- Build-logic removes repeated Gradle setup; it does not hide product
  behavior.
- Detect the repo's existing plugin ids, package, and plugin granularity first
  and extend them. Never copy a reference project's plugin list.
- Start with a few additive plugins per module family (for example an
  application, a library, a UI library, and a plain Kotlin/JVM library
  convention). Add a specialized plugin only after repeated module setup proves
  the need.
- A convention plugin may own:
  - toolchain, language, and target versions, and test options;
  - UI-framework enablement for the module family;
  - shared dependency bundles already used by several modules;
  - debug-only tooling dependencies;
  - static analysis and test wiring for tools the repo already configures;
  - opt-in compiler reports or metrics, scoped so normal builds stay quiet;
  - DI tool wiring only (the framework's Gradle plugin, its annotation
    processor, and its runtime/compiler dependencies), never product bindings.
- Expose shared test dependencies and test runner setup as dedicated test
  convention plugins, one per module family that needs it (for example
  platform and JVM). Higher-level plugins apply the test plugin instead of
  calling a shared configure helper.
- Keep static-analysis rule config at one explicit repo-root path (for example
  `config/<tool>/<tool>.yml`) as the single source of truth, with per-module
  baselines owned by each module. Register rule-set plugin dependencies in
  exactly one build-logic owner.
- A task needs a caller: a module that applies it, a CI step, or a documented
  command the repo already runs.
- Keep each plugin's package declaration aligned with its file path, and every
  plugin id resolvable to its implementation class.

## Cleanup Procedure

1. List every plugin id, its implementation class, its configure helpers, and
   the modules that apply it.
2. Search for real callers of each plugin id, task name, and configure helper
   (for example `rg "<plugin-id>|<taskName>|<configureFunction>"`).
3. Treat a plugin, task, or helper with no caller as a removal candidate and
   remove it unless the user asked to keep it.
4. Consolidate duplicate dependency blocks so each repeated block has exactly
   one owner.
5. Keep file moves separate from behavior changes.

## Do Not

- Do not put product routes, DI graph decisions, repository bindings, signing
  secrets, flavor or variant policy, generated module discovery, or one-off
  module behavior inside a shared convention plugin.
- Do not duplicate rule-set dependencies across plugins or keep shared tool
  config inside an app or feature module.
- Do not add Gradle tasks, staged-only checks, or Git hooks that nothing
  invokes.

## Verification

Verify in this order:

1. Compile the included build-logic build first (for example
   `./gradlew :build-logic:<convention-module>:compileKotlin`, using the repo's
   actual included-build path).
2. Compile or test one representative module per plugin family whose plugin
   changed, using the repo's variant- or target-qualified task names.
3. Do not use a full app build or `clean` as the first or only check.

Done means every plugin id resolves to its implementation class with a
matching package, no plugin id, task, or helper lacks a caller, each repeated
setup block has one owner, and the included build plus each affected family's
representative module compile.
