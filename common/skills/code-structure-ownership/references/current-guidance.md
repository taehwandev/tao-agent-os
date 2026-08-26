---
keyflow_id: sys_code_structure_ownership
status: stable
type: human-reviewed-needed
---

# Code Structure And Ownership

Use when deciding file layout, package layout, module boundaries, public
contracts, `api`/`impl` splits, or where new code should live.

Structure should make ownership, dependency direction, and review scope obvious.
Do not create modules or packages just because a pattern exists elsewhere.

The default choice is local or single-module code. Split only when the split
protects a real caller-facing boundary, extension point, dependency edge, or
ownership line.

For SOLID, Interface Segregation, Dependency Inversion, and DDD/domain-modeling
fit, also use `common/skills/solid-design-principles/SKILL.md`. In structure decisions,
SOLID means narrow caller contracts and dependency direction; it does not mean
creating layers or interfaces before a real boundary exists.

## Architecture-To-Structure Drill

Before writing code for work that crosses files, packages, folders, modules,
targets, source sets, or reusable test support, sketch the structure before
implementation. Keep it compact, but make the split explicit enough that a
reviewer can tell where new code belongs and what must not import what.

Use this order:

1. Name the behavior or capability being changed.
2. Name the owners that must stay separate: UI/rendering, state, domain policy,
   data/persistence, platform/external adapter, public contract, and testing
   support.
3. Choose the lowest ownership level that protects the boundary:
   file-private, package/internal, feature/module, feature-api contract,
   shared/core module, or public package/API.
4. Map the package or folder shape only for boundaries that have a real owner,
   allowed imports, forbidden imports, callers, and verification.
5. Split files by independently importable or testable owner before adding
   behavior. Before adding a non-private top-level helper to an existing
   development source file, count its current independent owners against the
   review limit. If the helper would cross that limit, place the concrete
   behavior in a purpose-named owner file with a matching subject test up front;
   do not hide it behind a broad `helper`, `utils`, or speculative policy layer.
6. Define public exports last; exports should be narrower than the
   implementation and grouped by contract family.
7. Inspect the executable review budgets before implementation: function or
   block size, per-file added lines, exported-owner count, changed-path limit,
   and any repo-local structure rules. When a new scaffold is entirely
   untracked, define one or more owned review pathspecs up front so starter
   examples and unrelated generated surfaces do not contaminate the task
   review. Split the implementation plan before writing code when its planned
   unit already exceeds a configured budget.

Before coding, enumerate every planned top-level export per runtime file exactly
as the review hook will count it. Exported type aliases, interfaces, option or
handle contracts, constants, classes, components, and functions are all public
owners; a type-only export is not invisible to the ownership budget. When the
list has more than one owner, keep a support type file-private when it has one
caller, or move an independently importable contract or behavior into its own
purpose-named file before implementation.

An exported object model plus exported parameter or result aliases is still
multiple public owners. When those aliases exist only to annotate the model's
single caller, keep them file-private and let the caller derive them with
`Parameters` or `ReturnType`; when callers need to import the aliases directly,
move that contract family to its own purpose-named owner file.

Make file-private intent visible to the executable review before coding. In
TypeScript and JavaScript, a non-exported top-level support type, interface,
option shape, or tiny helper still looks like a separate named owner unless its
identifier starts with `_`; use that prefix only for cohesive support owned by
the file's one public component, hook, or function family. Do not use `_` to
hide an independently testable, importable, stateful, or side-effecting owner;
move that owner to a purpose-named file instead. Other languages should use
their native private declaration syntax or the repository's explicit private
naming convention. Count the resulting non-private owners against the hook's
limit in the structure packet.

For non-trivial code work, the structure packet should include:

```text
behavior/capability:
chosen ownership level:
package/folder map:
file split:
allowed imports:
forbidden imports:
callers/tests:
nearest verification:
review budget and owned pathspec:
```

Treat this packet as a pre-code gate. If an agent cannot name the owner,
allowed imports, forbidden imports, callers/tests, and nearest verification for
the changed boundary, it must stop before adding files or moving code. Do not
let implementation discover the package structure by trial and error.

Do not start by putting every new file under one feature folder, `common`,
`shared`, `utils`, `helpers`, or another broad bucket and relying on future
cleanup. A feature folder is acceptable only when its child files or subfolders
still make the role boundaries obvious. A layer folder is acceptable only when
it enforces a real import rule, dependency direction, test boundary, or public
contract.

## Unit Size And Split Criteria

`references/unit-size.md` covers this: size as review pressure rather than
an automatic split command, the per-extension gates, and what earns an
exemption.

## Non-Negotiable Structure Stops

`references/structure-stops.md` covers this: the conditions that stop an
implementation outright, and what to do instead of continuing.

## Ownership Levels

Choose the lowest level that gives the code a clear owner:

```text
file-private -> package/internal -> feature/module -> feature-api contract
-> shared/core module -> public package/API
```

- File-private code is best for one caller and unstable details.
- Package/internal code is best for nearby collaborators with the same owner.
- Feature/module code is best for a cohesive behavior surface.
- Shared/core code is best for stable contracts used by multiple owners.
- Public package/API code needs compatibility, versioning, migration notes, and
  stronger tests.

## Module Split Choices

Most multi-module designs choose between two shapes.

## Decision Rule

Choose a single module unless the answer to at least one of these questions is
yes:

- Does another module need to compile against this contract without depending on
  the implementation?
- Does navigation, deep linking, plugin loading, dependency injection, or feature
  registration cross this boundary?
- Is this an extension point where another implementation can reasonably replace
  the current one?
- Would implementation dependencies leak heavy, platform-specific, paid, test,
  or optional dependencies to callers?
- Does the split remove a circular dependency, reduce build coupling, or let
  different owners change contract and implementation independently?

If all answers are no, keep the code local or in one module and revisit the
boundary when pressure appears.

## Modernization Drill

When modernizing an old or oversized codebase, separate structure moves from
behavior changes:

1. Inventory current imports, public exports, target/module membership,
   generated files, resources, tests, and runtime entry points.
2. Name the current owner and the intended owner before moving files.
3. Extract the smallest stable contract first: route data, component API,
   repository interface, platform adapter, use case, or typed model.
4. Compile or typecheck the contract boundary before moving implementation.
5. Move one feature, package, module, or source set at a time.
6. Keep compatibility shims only with an owner, removal condition, and test.
7. Remove old imports, duplicate exports, and dead target membership after the
   new boundary is verified.

Avoid combining broad moves with product behavior changes. If behavior must
change to make the split correct, call it out as a separate acceptance point.

When a move leaves work for a later task, record the hand-off so the next task can
plan against it rather than re-derive it:

- Any count carries the scope it was measured over — the paths searched and the
  matching rule. A bare number reads as repository-wide, so a package-local count
  recorded without its boundary sends the next task in at a fraction of the real size.
- Before recording that a symbol must move to a destination, check whether the
  destination already defines it, and state the result. When it already exists the
  remaining work is reference replacement and deletion of the original, which carries
  different risk than a move; writing "move" points the next task at the wrong plan.

### Single Module

Use one module or package when:

- The feature has one implementation and one owner.
- No other module needs to compile against its contract.
- Navigation, routing, or integration is local to the feature.
- The implementation dependencies are acceptable for all callers.
- The boundary is still changing and an interface would mostly duplicate files.
- Tests can cover behavior without isolating a public contract module.

This is the default for small or early features.

### API / Impl Pair

Use an `api` / `impl` split when at least one of these is true:

- Another module must depend on route contracts, events, interfaces, DTOs, or
  factories without depending on UI/data/framework implementation.
- Navigation, deep links, plugin loading, dependency injection, or feature
  registration needs a stable contract surface.
- Multiple implementations exist or are likely: fake/real, platform-specific,
  paid/free, local/remote, test/prod, or replaceable provider.
- The implementation has heavy dependencies that should not leak to callers.
- The split prevents circular dependencies or reduces build coupling.
- Different teams or agents can own contract and implementation independently.
- Contract compatibility matters for generated clients, SDKs, plugins, or public
  packages.

An `api` module should contain only stable contracts:

```text
interfaces, route/event contracts, public models, typed commands,
factory/provider contracts, small value types, compatibility docs
```

An `impl` module should contain implementation details:

```text
screens, adapters, repositories, framework code, internal mappers,
real/fake providers, DI bindings, platform integrations
```

Do not create an `api` module only to mirror architecture. If no caller can use
the API without the implementation, the split is probably too early.

### API / Impl / Assertions Trio

Use an `api` / `impl` / `assertions` split when tests need reusable support
without depending on production implementation details.

An `assertions` module or source set should contain:

```text
fake implementations, recording adapters, fixture builders, assertion DSLs,
test subjects, contract test helpers, deterministic clocks or dispatchers
```

Keep the dependency direction narrow:

```text
assertions -> api
tests -> assertions
impl tests -> impl plus assertions only when testing implementation behavior
```

Do not let `assertions` depend on production `impl` by default. Pulling in
production implementation code from a reusable test-support module usually
means the contract is not stable enough, the test belongs in the implementation
module, or the fake should be local to one test.

Create `assertions` only when at least one of these is true:

- two or more test boundaries need the same fake, fixture, recording sink, or
  assertion helper
- a contract module needs reusable conformance tests
- a route, repository, adapter, or platform boundary needs a deterministic
  test double that callers can share without booting the app shell
- the helper prevents tests from importing a heavy framework, platform, paid,
  or production implementation dependency

Keep one-off test data, previews, and test-only setup local until reuse is
real. Use plural `assertions` for module names so paths stay consistent across
repositories.

## Boundary Pressure Signals

Split or introduce a stronger boundary when these signals repeat:

- feature files import data-source, SDK, or platform implementation packages
- UI code reaches raw transport, database, file, or channel payloads
- shared packages need feature-specific flags, copy, analytics, or route
  decisions
- tests must boot unrelated app shells to exercise one state transition
- one implementation dependency forces all callers to carry a heavy optional SDK
- build changes require touching many unrelated target or package manifests
- a "common" folder has several unrelated owners and no stable public contract

When only one signal appears once, prefer a local cleanup before a module split.

## Package Layout

Prefer package names that express responsibility, not technical noise. Common
top-level groups include:

```text
api/ or contract/     public caller-facing contracts
impl/ or internal/    implementation details
route/                route keys, paths, navigation commands, or link contracts
event/                caller-emitted events and intent-like messages
schema/ or dto/       request/response shapes, validation schemas, generated contracts
command/ or query/    write commands and read queries when callers differ
model/                plain values owned by this boundary
state/                UI/application state and effects
component/            reusable UI or interaction pieces
data/                 persistence, network, cache, external data sources
domain/               product rules, use cases, policies
platform/             OS, runtime, SDK, filesystem, shell, browser adapters
testing/ or fixture/  test doubles, samples, deterministic fixtures
```

Use the repo's existing names first. Do not rename established packages unless
the rename itself is the task. Existing names still need review when a new
caller cannot infer the capability without reading implementation files.

## Boundary Rules

- Dependencies point inward or downward; implementation does not leak upward.
- Public contracts avoid framework-heavy types unless the platform is the
  contract.
- Domain and model layers avoid UI, persistence, transport, and platform types.
- UI layers do not own data source details or long-lived external side effects.
- Shared modules do not depend on feature implementation modules.
- Generated code, fixtures, and examples have explicit ownership.

## Review Checklist

- For files whose extension is in the development-file extension allowlist only,
  excluding tests, specs, mocks, fixtures, generated files, config/build files,
  Markdown, MDX, and prose docs unless repo-local policy opts them in, did the
  review check file size, added-line budget, function/block size, and
  independent owner count?
- Who owns this file or module?
- Which callers are allowed to import it?
- Is the public surface smaller than the implementation?
- Does any runtime file dump multiple independently named classes, components,
  hooks, handlers, services, repositories, adapters, DTOs, mappers, validators,
  jobs, commands, state owners, or platform bridges together without one caller
  contract?
- Does any runtime function, component, hook, handler, job, or script step span
  hundreds of lines because it mixes parsing, validation, IO, state changes,
  rendering, persistence, logging, navigation, retry, or recovery?
- Does each subject-specific unit test mirror its production owner's logical
  package or folder and use the subject name, rather than hiding in a broad
  feature or category test bucket?
- Does the split preserve future extension points through clear owners and
  caller contracts, instead of leaving everything in one file or adding
  speculative abstract layers?
- Does the split remove coupling or only add ceremony?
- Can the contract be tested without the implementation?
- Will a future implementation swap require changing callers?
- Are package names stable enough to keep?
- Can a new caller infer the boundary from the module/package name without
  opening implementation files?
- Did any broad name such as `app`, `common`, `shared`, `base`, `runtime`,
  `manager`, `helper`, or "feedback" pass a concrete capability note?

## Verification

For structure changes, verify the boundary, not only formatting:

- compile/typecheck all affected modules
- run focused tests for contract mappers, route resolution, or provider wiring
- inspect import direction for forbidden dependencies
- check generated clients, fixtures, or public exports when the API changed
- report whether the change chose single module or `api`/`impl`, and why
