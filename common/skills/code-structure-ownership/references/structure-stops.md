---
keyflow_id: sys_code_structure_stops
status: review
type: human-reviewed-needed
---

# Non-Negotiable Structure Stops

Use before writing code that crosses a boundary, to check whether any
condition here stops the change outright. For where new code belongs, use
`references/current-guidance.md`; for size as review pressure,
`references/unit-size.md`.

Do not continue implementation when any of these are true:

- The new change would add another unrelated responsibility to a file that
  already owns routing, rendering, state, data access, styling, and side effects.
- A single function, component, hook, handler, job, reducer, or script step would
  own more than one of these concerns: parse, validate, authorize, fetch, cache,
  map, render, mutate, persist, log, navigate, schedule, retry, or recover.
- The code needs separate tests, fixtures, previews, or manual checks for
  separate branches, but those branches are still hidden inside one unit.
- The proposed new file is a grab bag named `utils`, `helpers`, `common`,
  `misc`, `shared`, `manager`, `service`, `base`, `runtime`, `app`, or
  `platform` without a precise owner and contract.
- The proposed module, package, or folder name does not tell a caller what it
  can import, what it must not import, and which capability owns the code.
- The proposed function exists only to move an obvious line elsewhere, or it
  needs caller-specific flags to be useful.
- The split would create many tiny files with no stable owner, no testable
  contract, and no review benefit.

When a stop signal appears, make the smallest ownership split before adding more
behavior. The split can be file-private, package/internal, feature-local, or a
new source file; choose the lowest level that makes responsibility, dependency
direction, and verification obvious.

### Sibling Flow Owner Ledger

Product terms are not structure boundaries. A product state name or a new API
name or endpoint, such as `draft`, `pending`, `preview`, or `re-entry`, is not
evidence for a sibling screen, flow owner, state holder, or package.

Before creating a sibling flow owner, write down the actual behavior
differences from the nearest existing flow along five axes:

1. render
2. actions
3. state and lifecycle
4. side effects and navigation
5. verification

If the differences close over entry-time inputs only -- launch input, an
identifier's presence, a precondition, the first transition or submit, a
transient notice -- reuse the existing owner and express the difference as the
smallest parameter, state, or mode. A separate narrow orchestration owner is
justified only when it truly owns an independent side effect or lifecycle, and
even then, do not duplicate the whole screen or component family. When a new
flow owner is created, record the concrete behavioral difference and the
independent owner responsibilities in the ledger, and check that no parallel
component family implements the same render and actions after the first
transition.

### Function Or Block Split

Split a function, component, hook, reducer, handler, job, style block, or script
step when one of these is true:

- The unit combines multiple responsibilities such as parse, validate,
  authorize, fetch, cache, map, render, mutate, log, navigate, or persist.
- Branches describe different business cases, UI states, data sources, platform
  capabilities, or failure modes that can be named and tested separately.
- A pure calculation can be separated from IO, time, randomness, process state,
  global state, framework calls, or platform calls.
- The same rule, mapper, formatter, selector, style pattern, or error handling
  repeats in more than one real caller.
- A test, preview, fixture, or smoke path cannot exercise the behavior without
  booting unrelated systems.
- The best name for the unit contains "and", "or", "with", "misc", "common",
  "helper", or a caller-specific mode flag.

Keep the code local when the extracted helper would only rename an obvious line,
hide a necessary branch, require many caller-specific parameters, or have no
stable responsibility name.

### File Or Class Creation

Create a new source file, class file, CSS file, style module, or test fixture
when most of these are true:

- The new unit has a clear owner and can be named by responsibility, not by a
  vague bucket such as `utils`, `helpers`, `common`, or `misc`.
- It has a stable input/output, state, side-effect, rendering, styling, or
  contract surface.
- It can be tested, previewed, mocked, or reviewed without reading the whole
  caller.
- It isolates a real boundary: domain policy, state model, mapper, adapter,
  platform API, component contract, style primitive, fixture, or integration
  edge.
- The caller becomes smaller without losing the product policy, route decision,
  permission check, copy ownership, analytics ownership, or error ownership it
  should keep.

Do not create a new file or class only because a file is getting long. First map
the responsibilities, callers, state owners, side effects, and nearest checks.
If the new unit has one caller and no real boundary, prefer file-private or
package/internal code.

### Package Or Folder Creation

Create a new package, folder, namespace, target, or module when it protects an
import or ownership rule:

- Multiple files share one owner and are expected to evolve together.
- Callers should import a stable contract without seeing implementation details.
- A platform, SDK, database, filesystem, network, browser, shell, or paid
  dependency must stay behind an adapter boundary.
- Tests need a smaller unit than the app shell, server process, route tree, or
  renderer to verify behavior.
- The split prevents circular dependencies, broad manifest churn, or unrelated
  owners editing the same area.

A package or folder split unit should have one capability owner, one import
rule, one caller set or consumer family, and one primary verification path. Add
subfolders only when the child role can be imported, tested, reviewed, or
replaced separately. Typical child roles are contract/API, state, domain,
data, platform adapter, UI/component, route/event, schema/DTO, and
testing/assertions.

Do not treat a folder as structured only because files are grouped under one
feature name. A feature package that mixes screen rendering, state owner,
repository/client, DTO/schema, mapper, platform adapter, fixtures, and
assertions without role names and import rules is still a dump folder.

Keep the current package when the proposed folder would contain one or two
small unstable files, duplicate an architecture diagram without enforcing an
import rule, or become a grab bag for unrelated helpers.

### External SDK And Generated Integration Split

When integrating a platform SDK, marketplace surface, device capability,
identity provider, billing provider, or generated client, keep the generated or
provider-shaped code behind a narrow adapter boundary. Separate these roles when
they exist:

- source/provider schema or generated contract
- converter or mapper into local domain types
- request factory or command builder
- publisher/client/transport
- background worker, scheduler, receiver, or callback bridge
- verification fixture, fake, or assertion helper

Do not let a generated client or SDK sample become the feature architecture.
The feature should depend on local contracts and adapters; provider details
should stay in the integration boundary with focused tests.

### Package Boundary Note

Before creating or moving a package, folder, namespace, target, or module, write
a short boundary note in the implementation plan, task doc, PR description, or
review summary. The note must name:

- the owner and single responsibility of the new boundary
- allowed imports and explicitly forbidden imports
- the caller-facing exports, if any
- the callers or tests that benefit from the boundary
- the focused verification command or import-direction check

A new package is justified only when the boundary changes ownership,
dependency direction, review scope, testing scope, or replaceability. It is not
justified by "one file per type", "this architecture usually has folders", or
"the package looks cleaner".

For `api`, `impl`, and `assertions` layouts, split by contract surface and
consumer need, not by mechanical file count:

- `api` can group route contracts, events, commands, models, provider
  contracts, and small value types together while they share one import rule.
  Add subpackages, source files, or export modules when consumers should import
  one contract family, such as routes, events, schemas, DTOs, commands,
  provider ports, activity/launcher keys, or test fixtures, without the others.
- `impl` can group route mapping, rendering, registration, adapters, mappers,
  and state holders by behavior owner. Do not mirror every `api` file with an
  `impl` package unless the implementation dependency differs.
- `assertions` should split fixtures, builders, recording fakes, subjects,
  matchers, and contract tests by testing role. Do not create a package only to
  mirror each production type.

If the package boundary note cannot explain the allowed imports and who
benefits, keep the code in the existing package and split only files or
file-private helpers as needed.

### Hook And Repo-Local Structure Rules

Use three layers for package-structure discipline:

1. Pre-code route discipline: the `boundary plan` gate must name the chosen
   package/folder map, allowed imports, forbidden imports, callers/tests, and
   nearest verification before implementation.
2. Review-hook detection: the Tao Agent OS review hook checks changed runtime
   files for broad-package signals, new package boundary-note requirements, and
   repo-local structure rules. Treat hook failure as a structure bug, not as a
   reason to loosen the hook.
3. Repo-local rule files: each repo can define concrete package rules in
   `.agents/structure-rules.json`. A local-only override can live in
   `.tao/structure-rules.json`; this is useful while tuning rules but
   should not be the only source of truth for team workflows.

Supported rule shape:

```json
{
  "schema_version": 1,
  "allowed_new_paths": ["src/features/**", "src/domain/**", "src/platform/**"],
  "forbidden_new_paths": ["**/utils/**", "**/helpers/**", "**/misc/**"],
  "rules": [
    {
      "name": "domain_stays_out_of_ui",
      "paths": ["src/domain/**"],
      "forbidden_imports": ["src/ui/**", "@/ui/**"]
    },
    {
      "name": "feature_api_stays_narrow",
      "paths": ["src/features/*/api/**"],
      "project_import_prefixes": ["src/**", "@/**"],
      "allowed_imports": ["src/features/*/api/**", "src/domain/**", "@/domain/**"]
    }
  ]
}
```

Prefer `forbidden_imports` and `forbidden_new_paths` first because they are less
noisy. Use `allowed_new_paths` only when the repo has a stable source layout.
Use `allowed_imports` only with `project_import_prefixes` when the repo can
define a complete project-local import allowlist; otherwise external package
imports may create false failures.

The hook is intentionally read-only. It should report package and import
violations; the implementation agent must repair the structure or update the
repo-local rule with an explicit boundary decision. Do not hide structure drift
by moving the rule to an ignored local file or by removing the boundary-plan
gate evidence.

### Module-Level SOLID / ISP

Treat a module's public exports as an interface. Module-level ISP means callers
depend only on the module contract they actually need, not on a broad
implementation package.

Create or reshape modules around narrow contracts when:

- consumers need route contracts, events, commands, policies, models, factories,
  or repository ports without implementation dependencies
- read-only consumers should not import write commands, migrations, debug
  tools, lifecycle wiring, or registration code
- feature callers need stable API types without UI, data, SDK, database,
  platform, paid, optional, or test dependencies leaking into their graph
- tests need fakes, fixtures, or assertions without depending on production
  implementation modules
- a public barrel/export file is becoming a grab bag of unrelated symbols

Do not publish a module API that forces every caller to import all UI, domain,
data, platform, fixture, generated, and implementation details. A module split
is justified only when the narrower contract changes dependency direction,
build coupling, testability, or ownership.

### Assertions And Test-Support ISP

Treat a reusable assertions module as a public testing API. Keep its exported
roles narrow:

- fixtures create stable sample inputs
- recording fakes capture calls or events
- subjects/matchers assert one contract surface
- builders construct complex values without execution side effects
- contract tests verify substitutable implementations

Do not put all of these in one catch-all file or one broad fake when callers
need only one role. A test fake that requires unrelated no-op methods or
production implementation imports is an Interface Segregation failure, even if
it lives outside runtime source.

### Shared Code Promotion

Promote code to `common`, `shared`, `core`, a design-system package, or a public
package only when the caller contract is stable:

- At least two real callers or one explicit platform/public contract need it.
- Product copy, routing, permissions, analytics, tenant rules, billing rules,
  and workflow decisions remain in the caller.
- Inputs, outputs, errors, loading states, side effects, and customization points
  are explicit.
- The shared unit can change internally without forcing caller behavior changes.
- Tests, examples, previews, fixtures, or compatibility notes cover the shared
  contract.

Do not promote code only to reduce apparent duplication. Duplication is cheaper
than a shared API that needs flags, nullable options, hidden globals, or
caller-specific branches.

### Cross-Platform Commonization Gate

Promote code into a shared, core, common, multiplatform, or SDK-like boundary
only when the reusable contract is semantic rather than platform-shaped:

- Public names describe the domain or reusable capability, not one platform,
  framework, screen, or first caller.
- Platform objects stay behind adapters: `Activity`, `Context`, `Intent`,
  `NavController`, `View`, `Composable`, `UIViewController`, `URLSession`,
  browser globals, process APIs, database handles, and SDK clients do not leak
  into pure shared contracts.
- Side effects are explicit through suspend functions, commands, callbacks,
  ports, or adapters. Shared code should not hide lifecycle, thread, scheduler,
  filesystem, network, billing, credential, or analytics ownership.
- Runtime UI helpers live in a platform app/UI boundary. Pure core modules own
  models, policies, value types, ports, mappers, and route/event contracts.
- Assertions, fixtures, and fakes compile against the shared API contract, not
  the production implementation.
- Feature copy, route policy, analytics policy, permission prompts, and
  repository orchestration remain in the app or feature owner.

Cross-platform commonization fails when a common package exists only to avoid
duplication but still needs platform flags, nullable platform knobs, global
state, or caller-specific branches.
