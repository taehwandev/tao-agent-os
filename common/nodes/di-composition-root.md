---
keyflow_id: sys_common_node_di_composition_root
status: review
type: ai-generated
use_when: adding, moving, or reviewing dependency-injection bindings, qualifiers, multibindings, or graph assembly
skip_when: the change touches no object construction, binding, or graph wiring
---

# DI Composition Root

Applies to any constructor-injection setup: an annotation framework, a
compiler-plugin graph, a runtime container, or manual construction.

## Rules

- One composition root owns the graph. The app or entry target is the only
  module that sees every implementation; it assembles the graph and hands
  contracts to features. Libraries and features declare bindings or factories
  but never start a global graph or read process environment.
- Libraries use constructor injection with required parameters. A default
  argument such as `Deps(repo: Repo = FileRepo())` hides an implementation
  choice and defeats test substitution.
- Keep one graph technology per object graph. Mixing two DI frameworks in one
  graph, or half-migrating so some services come from the graph and others from
  hand-built holders, creates two composition roots.
- Put each binding in the module that owns the concrete implementation. Pure
  contract modules carry no DI annotations or framework dependency.
- Qualify same-type values: base URLs, string ids, network clients,
  dispatchers. Two unqualified providers of one type are incomplete even when
  the current graph happens to compile.
- Use multibinding (set/map contributions) or an injected registry for
  additive registrations such as route handlers, deep-link specs, initializers,
  and entry providers. The consumer injects `Set<Handler>` or a registry
  contract instead of building `listOf(FeatureHandler())`.
- The owner that consumes an injected set stays injectable too: a router
  factory, coordinator, or registry with an injected constructor, not a
  language-level singleton reaching into static state. Pure keys and specs may
  be singletons; graph assembly and runtime creation may not.
- A binding with one implementation that only hides one concrete type from one
  caller is not an additive registration; do not wrap it in a multibinding.
- Entry code (activity, window, app root) does not construct network clients,
  repositories, auth gateways, token or credential providers, route graphs,
  router factories, or production view-model factories once the graph exists.
  It injects a few coordinators.
- Before constructing a configured collaborator directly (`Foo()`,
  `Foo { ... }`, or stashed in a singleton, companion, or top-level private
  value), search for existing bindings of that type: injected constructors,
  provider and bind functions, qualifiers, and current injection callers.
- If a binding exists, verify its owner and qualifier semantics match the
  current capability before reusing it; type identity alone is not enough. A
  qualifier that owns one capability's serialization policy must not be
  borrowed by an unrelated capability. When owners differ, the current owner
  provides its own qualified binding or a narrower contract.
- Only when no binding exists, judge direct construction:
  - a pure value or leaf with no configuration, identity, lifecycle, I/O, or
    test-replacement point may be created at the nearest owner;
  - when configuration changes behavioral meaning or several callers must
    share one policy, the owning capability provides a qualified binding;
  - when the type owns lifecycle, resources, or an execution environment,
    inject it at the matching scope.
- Prefer a narrow pure API over a full configured instance when only one small
  operation is needed.
- A DI binding never hides a forbidden module edge. If a lower module needs
  behavior that lives in an implementation module, an interface in the lower
  module plus a binding in the implementation still hides a wrong edge unless
  that interface is the lower module's own contract.
- Tests replace the graph at the root: a test graph, test module, or manual
  construction through the same required constructors. Production code keeps
  no test-only construction branch.

## Do Not

- Do not keep a central `listOf(...)` in the app shell that enumerates every
  feature handler, initializer, or entry provider once growth is expected.
- Do not use a singleton object or manual service locator to avoid
  multibinding.
- Do not treat `private`, `internal`, or a singleton wrapper as making a
  configured collaborator a pure value; recreating an already-managed type
  locally causes configuration divergence and test blind spots.
- Do not place DI framework annotations in pure contract modules.
- Do not introduce a second DI framework beside the current one without a
  repo-level migration plan and an equivalence test.

## Verification

- Search for direct constructor calls of configured collaborators in entry and
  app-root code; each remaining one matches the direct-construction rules.
- Every same-type provider pair carries distinct qualifiers.
- Each multibinding consumer is itself injected, and no central list enumerates
  feature contributions.
- The module dependency graph still satisfies the repo's edge rules after the
  binding change.
- The graph builds, and a test replaces at least one binding through the root.
