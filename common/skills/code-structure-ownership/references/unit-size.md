---
keyflow_id: sys_code_structure_unit_size
status: review
type: human-reviewed-needed
---

# Unit Size And Split Criteria

Use when judging whether a file, function, or component has grown past what
one owner and one verification path can carry. For where new code belongs
and what must not import what, use `references/current-guidance.md`; for the
conditions that stop implementation outright, `references/structure-stops.md`.

Use code size as review pressure, not an automatic split command. Long code is
acceptable when it has one owner, one reason to change, and a clear verification
path. Short code still needs extraction when it mixes owners, side effects, or
contracts.

Apply the same ownership criteria to web, mobile, desktop, server, scripts, CSS,
styles, tests, and generated-adjacent glue. Apply strict size gates only to
changed files whose extension is in the development-file extension allowlist;
tests, specs, mocks, fixtures, generated files, config/build files, and docs are
reviewable but exempt from the hard size gates unless a repo-local rule opts
them in:

Pinned third-party source is also exempt from human-authored file and function
size gates only when it is isolated under a purpose-named `third_party`
boundary, copied byte-for-byte from one reviewed version, accompanied by its
license and provenance/checksum, and consumed through a narrow local adapter.
Local wrappers, patches, forks, and handwritten integration code remain subject
to the normal gates. Supply-chain, license, source-integrity, and behavior tests
replace size enforcement for the untouched upstream file; the exemption is not
permission to hide first-party code under `third_party`.

- Functions, methods, components, hooks, reducers, handlers, jobs, and scripts
  should be small enough to scan in one pass. About 40 to 80 lines is a normal
  review budget for orchestration code; over about 120 lines in runtime code is
  a hard review failure unless repo-local policy explicitly sets a different
  limit.
- Development source/style files should have one primary owner and one
  responsibility cluster. Over about 300 lines is review pressure: require
  structure-review evidence that names the owner, allowed imports, callers,
  tests, verification path, and split decision. A new file over about 500 lines
  fails review. An existing file already over about 500 lines must not gain
  another public owner, unclear responsibility, or hard-gate violation; when the
  change only edits an existing owner, require structure-review evidence instead
  of failing solely on pre-existing size. More than about 300 added lines in one
  development file fails review because it is usually a "dump it all here"
  signal.
- Apply the added-line gate to a newly introduced but still-untracked runtime
  file before building more behavior on top of it. If that file crosses the
  limit during a later task, split a real owner such as identity validation,
  mutation lifecycle, transport, or cleanup into its own purpose-named module;
  do not treat its presence before the current edit as an exemption.
- CSS and style files follow the same ownership rule. Do not group tokens,
  primitives, component variants, page layout overrides, and one-off fixes in
  one file only because they are all styles.
- Packages, folders, namespaces, targets, or modules are ownership boundaries,
  not storage bins. Create them only when they make allowed imports, dependency
  direction, tests, or review ownership clearer.

### All-Platform File And Type Baseline

Across web, mobile, desktop, server, scripts, styles, tests, docs-like source,
and generated-adjacent glue, every human-authored file must default to one clear
owner or role. Runtime files should have one independently importable owner.
Class-based code must keep one primary public or internal class per file. In
non-class shapes, keep one primary exported component, hook, handler, service,
repository, adapter, struct, enum, protocol, interface, object, function
family, or contract family per file.

Split aggressively at the nearest useful boundary before adding behavior when a
file has more than one named owner, review path, test path, side-effect owner,
or caller-facing contract. "One file per class" means one importable owner per
file; it does not require moving tiny private helpers, a sealed/algebraic value
family, or a framework-mandated route companion when they share one caller set
and one reason to change.

Do not approve runtime code that adds or keeps several independently named
owners in one file: classes, components, hooks, handlers, services,
repositories, adapters, DTOs, mappers, validators, jobs, commands, state
owners, platform bridges, fakes, fixtures, or assertion helpers. When a class,
interface, struct, protocol, object, function component, hook, handler, or
service is independently importable, testable, previewable, or reviewable, it
must live in its own purpose-named file.

For Kotlin contract and migration work, apply that rule without multiplying
modules or packages:

- each public `@Serializable` model, enum, sealed contract, repository, or
  event contract is an independently importable owner and gets a purpose-named
  file;
- related models stay in the same capability package unless their dependency
  direction, callers, or test ownership actually differ;
- internal network DTOs may share a file only when they are private/nested
  parts of one response aggregate; independently named request, response, or
  item DTO families get separate files;
- top-level mapper extensions stay together only for one response aggregate or
  one mapping pipeline. Distinct mapper families such as user, feed, and
  search mappers must not accumulate in a generic `*Mapper.kt` file merely
  because one repository consumes them.

This is a file-ownership rule, not a module-splitting rule. Prefer several
small purpose-named files in one stable package over new leaf modules or
packages that do not create a real dependency boundary.

Function-only files use the same rule. A file with free functions is acceptable
only when those functions form one cohesive contract family, pipeline, or
private support set for one exported owner. It is a structure problem when a
file collects unrelated functions because they are "helpers", "utils",
"common", or "small": parsing plus execution, read helpers plus mutating
commands, formatting plus I/O, policy plus transport, or unrelated caller sets
belong in separate purpose-named files. Tiny private helpers may stay near the
owner they support; independent importable functions should not share a file
only because the language does not use classes.

For Kotlin, extension functions on the same exact receiver may form one owner
cluster when the file has one responsibility name and the functions share one
caller contract and reason to change. Do not count that cohesive receiver family
as independent owners function by function. Extensions on different receivers,
or unrelated free functions collected by convenience, remain separate owners.

Do not:

- Keep multiple public or importable classes, components, services,
  repositories, adapters, handlers, widgets, ViewModels, or state owners in one
  runtime file because they are small, related, created together, or in the same
  feature.
- Hide mixed responsibilities behind nested classes, static methods, companion
  objects, extension files, partial files, barrel exports, or catch-all
  `types`, `models`, `services`, `helpers`, or `utils` files.
- Co-locate contracts and implementation, UI and state owner, DTO and mapper,
  route and rendering, handler and repository, platform adapter and product
  policy, or fixtures and assertions when callers or tests can use them
  independently.
- Split into ownerless tiny files only to satisfy a count. Every new file needs
  a responsibility name, allowed imports, review benefit, and nearest
  verification path.

### Responsibility-Based File Split

Do not pack separate roles into one source file only because they belong to the
same module, package, feature, or test-support area. A file should usually have
one responsibility cluster and one reason to change.

Split by role when a file starts mixing these categories:

- public contracts and implementation details
- fixtures/sample data and assertion logic
- recording fakes/spies and matcher or subject DSLs
- builders/factories and platform adapters
- parsing/normalization and execution/side effects
- route contracts, route resolution, and route rendering
- read-only helpers and mutating commands

This applies to `assertions`, `testing`, `fixtures`, and `dev` modules as much
as production modules. Test-support code is reusable code: callers should be
able to import a fixture, a recording fake, or an assertion subject without
pulling unrelated helpers or production implementation dependencies.

Keep a small one-file helper only when the roles are inseparable, have one real
caller, and can be reviewed in one pass. Once callers, responsibilities, or
verification paths differ, split the file before adding more behavior.

### Change-Resilient Authored Content

Apply the ownership drill to presentations, tutorials, onboarding flows,
wizards, catalogs, timelines, static reports, scripted demos, and other ordered
content that is rendered in more than one mode. These surfaces are not safely
structured when the prose lives in one file but counts, durations, headings,
navigation bounds, or semantic visual labels are repeated in components and
tests.

Prefer one typed authored-content root with multiple derived projections:

```text
typed authored config -> pure derived metadata -> stage/read/overview/timer
```

- The authored config owns durable facts: title or thesis, ordered items,
  item copy, notes, links, semantic visual labels, and per-item duration.
- Pure derivation owns counts, total duration, progress bounds, timer
  thresholds, and labels that are mathematical or grammatical projections of
  those facts.
- Keep the derived model boundary subject to the same one-owner rule as runtime
  behavior. If a definition, derived metadata shape, timer policy, and completed
  presentation are independently named public contracts, give each contract a
  separate owner file even when one factory composes all four. Relatedness is
  not a reason to create a multi-owner type bucket.
- When one authored presentation has distinct stage and presenter windows,
  treat the message contract, transport adapter, stage state bridge, and
  presenter remote bridge as separate owners when callers import them
  independently. Do not hide two exported synchronization hooks and several
  exported transport types in one broad `sync` file; enumerate these exports in
  the structure packet before coding.
- Rendering, navigation, timer, overview, print, and read-mode consumers import
  the config or its derived metadata. They must not retype the same facts as
  local constants or display strings.
- Reused copy has one semantic owner. Reference the same field or canonical
  constant instead of copying the literal into another item, header, metadata
  block, or test.
- Meaning-bearing visual text belongs with the authored item when changing the
  narrative should change that text. Reusable scenery, layout, motion, and
  styling primitives stay in rendering or style owners.
- Adding, removing, reordering, or retiming an item should normally change the
  authored config only. A consumer should change only when its behavior or
  presentation contract changes, not to synchronize a stale count or duration.

When a fixed global budget is intentionally independent from the sum of item
durations, encode both facts explicitly and validate their relationship. Do not
silently let a timer policy, agenda label, and item durations drift apart.

Tests should check invariants and projections rather than duplicate product
facts or parse source text. Useful checks include unique stable ids, valid
ordering, item-duration sum versus the declared budget, derived count and timer
values, and confirmation that every rendering mode consumes the same ordered
collection. A test that hard-codes the same count or duration without deriving
it from the canonical config protects the duplication instead of the product.

Keep a single authored file while it has one owner and remains reviewable.
When volume creates review pressure, split by a stable act, chapter, section,
locale, or ownership boundary and aggregate those parts through one canonical
ordered export. Do not default to one file per slide, step, or item, and do not
introduce a CMS or runtime editor when the content is static and developer-owned.

For these surfaces, extend the structure packet with the authored-content
owner, derivation owner, rendering projections, invariants, and the expected
change path for copy edits, reordering, and retiming.

### Test Subject Ownership

A subject-specific unit test belongs to the production owner it verifies, not
to a broad feature or category bucket. Mirror the production owner's logical
package, namespace, or folder under the test source root, and name the test
after that owner using the repository convention, such as `<Subject>Test`.

Do not gather unrelated class, object, component, ViewModel, repository, or
mapper tests under a generic feature test file merely because their behavior
participates in the same product flow. Each such test should make its production
subject discoverable from both its path and its name.

Cross-owner contract, integration, migration, or end-to-end tests may live at
the boundary they exercise. Name those tests after the contract or flow, list
the participating owners, and keep subject-specific unit behavior in each
owner's mirrored test location.

### Contract Family Split

Apply contract-family splits across every language and platform. A Kotlin
package, TypeScript module or barrel file, Swift target, Dart library, Python
package, server folder, CSS module, or test-support package is still a public
interface when another caller imports it.

Do not keep unrelated caller-facing contract families in one catch-all file,
module, namespace, or export surface. Split when the same API area starts mixing
families such as:

- routes, route events, deep-link matchers, and rendering or execution adapters
- request/response DTOs, validation schemas, generated clients, and route
  handlers
- read queries, write commands, mutation policies, and background jobs
- component props, feature policy, analytics names, and platform launchers
- fixtures, builders, recording fakes, assertion subjects, and contract tests

Use names that describe the import boundary. Examples: `route`, `event`,
`schema`, `dto`, `command`, `query`, `adapter`, `fixture`, `assertion`,
`activity`, `platform`, or the repo's established equivalents. Keep a single
contract file only when it contains one small contract family, has the same
caller set, and has one reason to change. Do not split mechanically into one
folder per type when the caller-facing import boundary is identical.

Barrel or index files are allowed only as narrow compatibility surfaces. They
must not hide a grab bag of unrelated route, schema, event, UI, data, platform,
and testing exports behind one convenient import.

### Capability Naming And Boundary Inference

Names are part of the architecture contract. A future agent or maintainer should
be able to infer the owner, allowed imports, and reusable capability from the
module, package, namespace, target, or folder name before opening every file.

Do not create or keep a broad boundary named `app`, `core-app`, `core-ui`,
`runtime`, `base`, `common`, `shared`, `platform`, `manager`, `helper`,
`service`, `utils`, or a similarly vague word unless the repo already defines
that name as a stable capability family and the next package level makes the
capability precise.

Do not name a reusable module after:

- the first app, feature, screen, or caller that happened to need it
- the current implementation surface when the reusable capability is narrower
- a broad user reaction such as "feedback" when the code actually owns notices,
  toasts, snackbars, dialogs, alerts, error presentation, permission prompts, or
  another concrete capability
- an inheritance shape such as "base" when the boundary really owns lifecycle
  setup, routing handoff, environment creation, or platform adapters

Before adding, keeping, or renaming a broad boundary, write the boundary note in
terms of the concrete capability. If the note cannot say what callers may import
without using words such as "misc", "common things", "app stuff", "shared
helpers", or "feedback", the name is not ready.

Keep pure contracts, platform runtimes, app-shell orchestration, design-system
primitives, test assertions, and feature policy in separate boundaries unless
one explicit owner and import rule covers them all. A module that mixes Activity
templates, route execution, notification/toast rendering, visual tokens,
repositories, and product policy is a catch-all module even when it compiles.
