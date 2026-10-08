---
keyflow_id: sys_kmp_node_di_metro
status: review
type: ai-generated
use_when: Adding or changing a Metro dependency graph, provider, binding or graph factory in a Kotlin Multiplatform app, or deciding where a new dependency gets constructed.
skip_when: The project uses another DI framework or manual wiring only; apply the parent composition-root node directly.
refines:
  - common/nodes/di-composition-root.md
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP Dependency Injection With Metro

The parent node owns composition-root rules. This node applies them to Metro
(`dev.zacsweers.metro`), a compile-time DI compiler plugin.

## Rules

- Apply the Metro Gradle plugin only to the app target that owns the graph.
  Library modules (`core:*`, `feature:*`) keep plain constructors and do not
  depend on Metro, unless the repo deliberately adopts contributed bindings
  for a module and documents that boundary.
- The graph is an interface annotated `@DependencyGraph` in the app target.
  Runtime inputs (project root, launch arguments, platform handles) enter
  through `@DependencyGraph.Factory` parameters marked `@Provides`; create
  the graph with `createGraphFactory<...>()` at the entry point.
- `@Provides` functions on the graph construct library types by calling
  their public constructors or factory functions. Name the provider after
  the contract it supplies and return the contract type.
- Expose only what entry points need as graph accessors (repositories, state
  holder factories). Screens never receive the graph object itself.
- Scope long-lived singletons explicitly with the graph's scope annotation
  (for example `@SingleIn(AppScope::class)`) and give each a release path when
  it owns a process, database or file handle.
- Qualify same-typed values (`@Named` or a custom qualifier) instead of
  wrapping primitives in throwaway types without meaning.
- Tests construct the graph through the same factory with fake inputs, or
  bypass the graph and call constructors directly for unit tests.

## Do Not

- Do not reference graph types, Metro annotations or `createGraph*` from
  `feature:*`, `core:*` or stateless composables.
- Do not hide a forbidden module dependency by providing it from the app
  graph into a module that may not import it.
- Do not add a provider for a type that already has one; search the graph
  first.

## Verification

- The app target compiles (Metro reports missing or duplicate bindings at
  compile time) and the entry point launches.
- `rg "dev.zacsweers.metro"` matches only the app target (or the documented
  modules) after the change.
