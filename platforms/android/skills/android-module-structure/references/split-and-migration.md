---
keyflow_id: sys_android_split_and_migration
status: review
type: human-reviewed-needed
---

# Android Split Decision And Migration

Use when deciding whether an Android feature, repository, or test
helper earns its own module, and when sequencing the move from an
existing layout to that split.

## Split Decision

Choose a single feature module when:

- only one screen or flow owns the code
- no other module needs to compile against the contract
- navigation is local or can be wired from the current module
- implementation dependencies are acceptable to callers
- the boundary is still changing quickly

If the repo's architecture baseline uses feature module families, keep the
reason explicit. The `api` module is the caller-facing interface: role-sized
contracts, the destination type and its navigate action, deep-link and route
events, ports, entities, and delegates. The `impl` module owns the screen-level
feature, including its holder composable, ViewModel, state, mapping, content,
entry binding, and any Activity or other platform entry. Do not let the split
become files that mirror each other without reducing imports, cycles, test
weight, or platform leakage.

Choose `feature-api + feature-impl` when another module must reach the feature:

- another feature, holder, app module, or navigation graph must reference the
  destination without importing the screen implementation
- route data, deep links, results, Compose entrypoints, or public events cross
  the feature boundary
- the feature is entered through an Activity or another platform shell
- the split prevents circular dependencies

Add `feature-ui` on top of that pair only when a named consumer outside `impl`
must render the same concrete surface: a second host, another form factor, a
shared container, or a test target that must not pull in the Android entry.

Use these extraction checks:

- Name the caller and the destination or entry contract it imports. If that
  caller only navigates, it is served by `api` and no `ui` module is justified.
- Name the consumer that renders the surface outside `impl`. An internal
  package, a preview, or the feature's own Activity wrapper is not that
  consumer.
- Move what that consumer actually reuses: the stateless content, its visual
  models, callbacks or slots, and previews when the consumer supplies state;
  the holder composable, ViewModel, orchestration state, and mappers as well
  when it needs the working feature. Do not leave a second copy in `impl`.
- Keep the `NavEntry` or entry-provider registration, Activities, manifests,
  Intents, Activity launch/result handling, SDK entry adapters, and platform DI
  in `impl`.
- Let `impl` depend on `api + ui`; never let `ui` or `api` depend on `impl`.
- Prove `ui` with the named consumer, a preview, or a test that does not
  include `impl`.
- Promote only domain-free, broadly shared primitives to the design system;
  keep feature-specific reusable surfaces in the feature module.

An Activity wrapper is a reason to keep `impl`, not a reason to extract `ui`.
The Activity reads the platform request, hosts the feature content, and maps
the result back to Android; when nothing outside it renders that content, the
content stays beside it.

For Navigation 3-style apps, keep destination types, route data, deep-link
contracts, results, navigate actions, and public route events in the feature
`api` module. Keep `NavEntry`, entry-provider builders, the holder composable,
ViewModel, composable content, and screen state in `impl`. The app module
assembles entry providers, synthetic back stacks, host/scheme policy, and
Activity task-stack behavior.

Official Navigation 3 documentation calls the content module `impl`, and this
family uses the same placement: destinations in `api`, navigable content in
`impl`, and a `ui` module only when a named consumer outside `impl` renders the
same surface.

Choose a repository `api` plus implementation pair when:

- feature modules need a repository interface and stable entities
- DTOs, Retrofit/Room/DataStore, SDK clients, or cache implementations should
  not leak into callers
- test modules need an assertion or fake implementation
- multiple repository implementations can exist for flavors, dev tools, or
  platform-specific behavior

Do not create `api` modules that contain only one unused interface and no caller
that benefits from avoiding the implementation dependency.

Start the data layer coarse: one data `api` plus implementation pair for the
repo, partitioned inside by capability packages (resource, storage, backend
capability) before any module split. Do not split data modules to mirror
screen or feature names. Split a separate data module only when multiple
feature callers need the capability independently, a heavy SDK, database, or
cache dependency needs isolation, a flavor or dev/prod implementation swap is
realistic, build or test isolation is required, or ownership genuinely
separates.

Choose an `assertions` module or source set when:

- two or more test boundaries need the same fake, fixture, recording helper, or
  assertion DSL
- a route, repository, adapter, or platform boundary needs reusable contract
  tests
- tests should compile against the stable API contract without depending on the
  production implementation module
- the reusable helper avoids booting the app shell, DI graph, network stack,
  database, WebView, camera, billing, or other heavy implementation dependency

Do not create an `assertions` module for one test, preview-only sample data, or
a helper that must import production implementation code to be useful. In those
cases, keep the helper local or put the test in the implementation module.

Inside an Android `assertions` module, split source files by testing role rather
than by convenience:

- fixtures or sample route/data keys in one focused file
- recording fakes/spies in files named for the contract they record
- assertion subjects or matchers in files named for the contract they assert
- builders/factories in files named for the value they construct
- contract tests in their own test source files

Do not put every fake, fixture, route key, recorder, and assertion DSL into one
module-level bucket file. The module is already the shared boundary; files
inside it still need SOLID responsibility and Interface Segregation. A test
that needs only a route fixture should not import an Activity launcher fake,
repository recorder, WebView helper, or production implementation dependency.

Choose a `core-app` module when:

- the shared code needs Android or Compose runtime APIs
- the code is app-shell infrastructure reused by several features, such as
  notice or alert hosts, permission adapters, ActivityRoute launching, WebView
  runtime, resources, or app-level composition helpers
- the caller-facing API can stay free of feature copy, product route policy,
  analytics policy, repository calls, and screen-specific state

Keep pure contracts in `core`; move Android/Compose runtime commonization to
`core-app`, `core-ui`, or a repo-specific runtime module only when a real
shared app-runtime boundary exists.
Avoid broad `BaseActivity`, `BaseFragment`, or universal `BaseViewModel`
hierarchies. Prefer small contracts such as app environment, route coordinator,
notice host, permission host, and platform adapter interfaces.

For ViewModel-adjacent runtime capabilities, prefer interfaces and delegates
over inheritance. A notice, router, deep-link, permission, or launcher delegate
can own reusable effect plumbing, but the ViewModel remains the action/state
owner. The delegate exists to avoid broad base classes, not to hide product
policy or screen state.

A reusable Compose Activity base may own only the narrow Activity template:
edge-to-edge setup, content installation, lifecycle-aware intent/deep-link
handoff, environment access, and explicit extension hooks. Keep product route
registration, Navigation 3 entry-provider assembly, feature screen mapping,
ViewModel creation, repository calls, analytics, and screen state outside that
base.

## Migration Strategy

When modernizing an old Android feature:

1. Record the current owner boundary and imports before moving files.
2. Extract stable contracts first: route data, repository interface, public
   entities, or UI component API.
3. Compile or typecheck the contract boundary before moving implementation.
4. Move implementation behind the contract in the smallest reviewable slice.
5. Add or update tests/previews for the moved boundary.
6. Remove only old code that is no longer referenced.

For a `ui` extraction, move the surface the named consumer reuses as one unit —
the stateless content and its models, plus the holder, ViewModel, and mapping
when the consumer needs the working feature — and leave the entry binding and
Android entry in `impl`. Change the
ViewModel to depend on stable repository or domain ports, compile the named
consumer against `api + ui`, and verify the feature with fake ports before
adapting `impl` to delegate. Do not move concrete repository implementations,
Activity, manifest, Intent, or Activity result handling into `ui` merely to make
it appear self-contained.

Do not combine broad module moves with behavior changes unless the behavior
change is necessary to make the split correct.

## Split Hazards

These failures show up while performing a file split, not while deciding it.

Dedupe before widening visibility. A helper that was file-private has to widen
to `internal` when it moves into its own file. If a sibling file in the same
package already declares a private helper with the same name and receiver, both
are top-level in that package and Kotlin reports overload ambiguity at the
existing call sites; the same-file declaration does not win. Before widening,
search the destination package for top-level private declarations with that
name and receiver. Duplicates are usually copies that have already drifted, so
fold them into one shared `internal` file as part of the same change and delete
every copy. Plan a split that crosses a package boundary as dedupe-then-move,
not move-then-discover.

Relocation and rewrite are one unit. When a split also moves a file to another
package, stage the move and the content rewrite together and treat both the old
and the new path as in scope. Git rename tracking, review tooling, and
mutation-scope guards all see both records change, so a scope naming only the
destination path is incomplete and can be rejected. Rewriting the file after
the move was already recorded separately leaves a rename record that matches
neither declared path.

Two more apply when the split is mechanised rather than typed out by hand, and
both are silent.

Key extracted blocks by position, not by declaration name. Overloaded top-level
functions share one name, so a name-keyed extraction keeps only the last and
deletes the rest. A file holding ten `toUi` overloads lost nine of them this
way. Nothing failed loudly: a dropped private helper still compiles whenever no
surviving code calls it. Verify a split by comparing the declaration count
before and after, not by the build alone, and keep the original until that
count matches.

Treat conventionally-bound and aliased imports as used. Pruning imports by
scanning the moved code for each import's name removes two kinds that are
genuinely needed. Kotlin property delegation resolves `getValue` and `setValue`
by convention, so those names never appear as identifiers and every
`by`-delegated property breaks once the import is dropped — including
`mutableStateOf` and `rememberUpdatedState` in Compose. And an aliased import
binds its alias, not the last segment of its path, so matching on the path tail
finds nothing and drops the alias the code actually uses.
