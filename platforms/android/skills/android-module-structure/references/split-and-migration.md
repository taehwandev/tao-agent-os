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

If the repo's architecture baseline is `api` plus implementation modules, follow
that convention, but keep the SOLID reason explicit. The `api` module is the
caller-facing interface: role-sized contracts, route/deep-link events, ports,
entities, and delegates. The implementation module owns concrete screens,
ViewModels, adapters, mappers, DI bindings, platform launchers, and runtime
wiring. Do not let the split become two files that mirror each other without
reducing imports, cycles, test weight, or implementation leakage.

Choose a `feature-api` plus `feature` implementation pair when:

- another feature, holder, app module, or navigation graph must reference the
  destination without depending on implementation
- route data, activity/fragment/Compose entrypoints, or public events cross the
  feature boundary
- the implementation has heavy dependencies such as camera, webview, ads,
  billing, SDK integrations, or large UI libraries
- the split prevents circular dependencies
- a fake, dev, paid/free, flavor-specific, or replaceable implementation is
  realistic

For Navigation 3-style apps, keep navigation keys, route data, deep-link
contracts, and public route events in the feature `api` module. Keep `NavEntry`,
entry-provider builders, composable content, and screen state holders in the
feature implementation or app-shell module. The app module assembles entry
providers, synthetic back stacks, host/scheme policy, and Activity task-stack
behavior.

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

Do not combine broad module moves with behavior changes unless the behavior
change is necessary to make the split correct.

