---
keyflow_id: sys_4d909f6cacff
status: stable
type: ai-generated
---

# Testing Principles

Use when choosing, adding, reviewing, or reporting tests, fixtures, snapshots,
manual smoke checks, or verification evidence.

When writing or meaningfully reviewing test code, also open
`common/skills/scenario-driven-testing/SKILL.md`. Test cases should be framed as actor
scenario -> action -> response condition -> observable success, failure,
exception, or recovery result before dropping down to framework-specific
Arrange/Act/Assert code.

Test behavior users or other code depend on.

## Decision Rule

Choose the smallest test that can fail for the behavior being changed. Broaden
only when the risk crosses a boundary that the smaller test cannot see.

Do not add a test only because a file changed. Add or update a test when the
change affects a product rule, public contract, state transition, mapper,
permission, persistence, cache, platform adapter, release behavior, or known
regression.

## Test-First

Use test-first when the expected behavior is clear enough to name before
implementation. Design the scenario and the smallest failing test before
changing production code, then implement only enough code to pass that test and
the adjacent regression checks.

Test-first is not a reason to guess missing product behavior. If the expected
outcome, permission rule, data-loss rule, migration behavior, or error copy is
unclear, clarify the source of truth before writing the test.

For bug fixes, reproduce the failure with a focused failing test when practical.
For new behavior, write the test against the public boundary or state transition
the caller depends on, not private implementation steps.

## Unit Test F.I.R.S.T. Check

When adding or reviewing unit tests, check that they are:

- Fast: narrow enough to run during normal local development.
- Isolated: independent from other tests and external mutable state.
- Repeatable: deterministic across machines, time, order, locale, and network
  availability.
- Self-validating: assertions decide pass or fail without manual log inspection.
- Timely: written before or alongside the production change while the expected
  behavior is still explicit.

## Prioritize

1. Product rules and permissions
2. Data mapping and API contracts
3. State transitions and errors
4. Critical user flows
5. Bug regressions

## Cover

- success
- loading
- empty
- permission denied
- validation error
- API/network error
- boundary values, including zero, minimum, maximum, overflow, malformed,
  stale, duplicated, cancelled, and unavailable inputs

## Prefer

- Unit tests for pure policy, mapper, validator logic.
- State tests for ViewModel, hook, reducer, store.
- UI tests by visible text, role, label, and interaction.
- E2E only for high-value cross-boundary flows.

## Match Test To Boundary

| Changed boundary | Preferred evidence |
| --- | --- |
| Pure function, mapper, parser, formatter, policy | Unit test with normal, missing, invalid, boundary, and duplicate cases |
| State owner, reducer, ViewModel, hook, store | Transition test for action -> state/effect, including failure and retry |
| UI component or screen | Component/UI test, preview, screenshot, or manual path for visible states and user intent |
| API route, DTO, event, webhook, generated client | Contract or request/response test plus affected caller check |
| Persistence, cache, migration, sync | Read/write/update/delete, stale data, invalidation, rollback, or compatibility check |
| Permission, auth, tenant, billing, privacy | Allowed and denied paths, stale/revoked state, and boundary enforcement |
| Platform, filesystem, shell, browser, SDK, background work | Adapter test, fake integration, lifecycle/cancellation check, or manual smoke path |
| Release, package, signing, deployment | Dry run, build/package check, staging/manual smoke, or rollback note |

## Isolation

- Mock at external boundaries: network, database, filesystem, clock, random,
  payment, email, analytics, and platform APIs.
- Prefer deterministic fixtures and builders over copied production payloads.
- Keep fixtures close to the test or shared contract they prove.
- Do not weaken assertions only to make a flaky test pass; identify the unstable
  boundary first.
- Test permission, tenant, billing, migration, and generated-client contracts at
  the boundary where they can actually fail.

## Stack Discovery For Tests

Before adding a test in an unfamiliar repo, discover the existing test stack:
unit framework, integration harness, UI framework, screenshot/snapshot tooling,
dependency injection, mocking/fake style, device/browser/runtime runner, and E2E
scope. Prefer the repo's existing framework and fake patterns before introducing
new test libraries or broad mocks.

For UI changes, cover the states and form factors affected by the change:
common, loading, empty, error, disabled/read-only, permission denied, long text,
theme, font scale, and the relevant screen or window sizes. Use screenshots or
previews only when they prove the changed visual contract; pair them with
focused assertions for behavior.

## Test File Organization

Choosing what to test is not enough; a repo also needs a rule for **where a
test lives**, or coverage keeps landing in whichever file was already open.
Without this rule a single file can grow to thousands of lines -- at that size
the file stops being a safety net and becomes its own maintenance risk: harder
to navigate, harder to review a diff against, and more likely to produce merge
conflicts between unrelated changes.

- **Mirror the source module.** The primary placement rule is structural, not
  judgment-based: `scripts/agent_repair_ledger.py` -> `tests/test_agent_repair_ledger.py`.
  This is the only rule that requires no scenario/type classification and
  therefore never becomes ambiguous.
- **Split scenario or type inside one file, not across files.** Group a
  module's success/error/boundary cases or unit/integration variants into
  separate test classes within the mirrored file (for example
  `RepairLedgerBoundedAttemptTests`, `RepairLedgerConcurrencyTests`), not into
  separate files. Splitting by scenario/type instead of by module scatters one
  module's behavior across many files and makes "where is this test" and
  "where should this new test go" ambiguous again.
- **Cross-module flows are the one exception.** An end-to-end or CLI rehearsal
  that exercises several modules together does not belong to any single
  mirror file; name it for the flow, e.g. `test_<flow>_end_to_end.py`.
- **When no mirror file exists yet, create one.** Do not append a new test to
  the nearest large file just because it already has related-looking tests.
  If `tests/test_<module>.py` does not exist, create it.
- **Tests move with the class.** When a class moves to another module or
  package, its test files and their fakes/fixtures migrate in the same change.
  A test left behind still compiles, so it hides the broken boundary while
  forcing the class to keep test-only public API -- thin public delegations to
  internal collaborators kept alive only so the old test can reach them. On
  migration, give internal collaborators their own same-module tests, delete
  the test-only public delegations, and verify the move with pre/post
  scenario-count parity from the test report.
- **Size budget: about 3x the production file limit.** A test file's file-size
  ceiling is three times the production source-file limit (currently 500
  lines, so ~1,500 lines for tests) -- wide enough for setup/fixtures/one
  scenario per case, not unbounded. `agent_review_structure.py`
  (`REVIEW_TEST_FILE_LINE_LIMIT`) enforces this in the review hook; when a
  mirrored test file would cross it, split by scenario/type into test classes
  first, and only split into additional files if a single module's own test
  surface is large enough to need it.
- **Migrating an existing oversized file is safe to do in one pass.** Unlike a
  production refactor, a test-file split is self-verifying: after moving tests
  into their mirrored files, the full existing suite passing with the same
  test count proves the split preserved behavior. Prefer one bounded split
  over incremental extraction that leaves the file oversized for a long
  transition period.

## Do Not

- Do not replace a missing high-risk test with a formatter, typecheck, or
  snapshot update.
- Do not snapshot broad output when a focused assertion would explain the
  behavior.
- Do not mock the unit under test so deeply that the product rule cannot fail.
- Do not add fixtures copied from private production data.
- Do not mark behavior verified when only mocked, placeholder, or happy-path
  behavior ran.
- Do not trust a passing test you have not shown can fail. For a guarantee that
  matters, add a negative control: inject the violation the test is supposed to
  catch and confirm the check actually fails. A test that stays green when the
  property is broken proves nothing.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "The change is small." | Check whether the risk is small; add the nearest test when a contract or state transition changed. |
| "The compiler passed." | Compiler success does not prove behavior, permissions, persistence, UI, or release paths. |
| "Manual testing is faster." | Record the manual scenario and add automated coverage when the risk is recurring or high. |
| "The existing test is flaky." | Diagnose the unstable boundary; do not weaken assertions to get a pass. |

## Red Flags

- A behavior change has only formatting, lint, or typecheck evidence.
- A high-risk path is tested only through mocks of the unit under test.
- A snapshot update hides a product or layout change without a focused
  assertion.
- Tests cover the happy path but omit error, empty, permission, stale, or
  unavailable states that the changed boundary can produce.
- A guarantee is asserted only by tests that pass, with no negative control
  proving they fail when the property is violated.

## Report

For automated checks, report command, result, and what boundary it proved. For
manual checks, report scenario, environment, action, expected result, and
observed result.

If a test cannot run, state the command skipped, why, and residual risk.
