---
keyflow_id: sys_common_testing_md_skill
status: stable
type: ai-generated
required_contract: core
---

# Testing Principles

Use when choosing, adding, reviewing, or reporting tests, fixtures, snapshots, manual smoke checks, or verification evidence.

## Read

The core below is the required contract. When writing or meaningfully reviewing test code, also open `common/skills/scenario-driven-testing/SKILL.md`. Open `references/current-guidance.md` only for an unresolved in-scope question:

- `## Match Test To Boundary` for which evidence fits a changed boundary.
- `## Stack Discovery For Tests` for an unfamiliar test stack or UI state/form-factor coverage.
- `## Test File Organization` for placement, splits, migrations, size budget.
- `### Optional Python unittest verification` for the `verify --test-pattern` tests gate.
- `## Common Rationalizations`, `## Red Flags` when weighing whether evidence is enough.

## Must

- Frame cases as actor scenario -> action -> response condition -> observable result before Arrange/Act/Assert.
- Choose the smallest test that can fail for the changed behavior; broaden only when risk crosses a boundary it cannot see.
- Do not add a test only because a file changed. Add or update one when the change affects a product rule, public contract, state transition, mapper, permission, persistence, cache, platform adapter, release behavior, or known regression.
- Test-first when expected behavior can be named: smallest failing test, then only enough code to pass it plus adjacent regressions. Bug fixes: reproduce with a focused failing test when practical. Test the public boundary or state transition, not private steps.
- Unit tests are F.I.R.S.T.: fast, isolated, repeatable (time, order, locale, network), self-validating, timely.
- Prioritize product rules and permissions, data mapping and API contracts, state transitions and errors, critical flows, bug regressions.
- Cover what the boundary produces: success, loading, empty, permission denied, validation error, API/network error, boundary values (zero, min, max, overflow, malformed, stale, duplicated, cancelled, unavailable).
- Prefer unit tests for pure policy/mapper/validator logic, state tests for state owners, UI tests by visible text, role, label, interaction; E2E only for high-value cross-boundary flows.
- Mock at external boundaries (network, database, filesystem, clock, random, payment, email, analytics, platform APIs). Test permission, tenant, billing, migration, generated-client contracts where they can fail. Use deterministic fixtures near what they prove; never copy private production data.
- Discover and reuse the repo's existing test stack and fake patterns before new libraries or broad mocks.
- UI changes: cover affected states and form factors; screenshots/previews only when they prove the visual contract, paired with focused assertions.
- Place tests in the mirrored module file (create it if missing, not the nearest large file); split scenario/type into classes inside it; name cross-module flows `test_<flow>_end_to_end`. Tests and fakes move with the class in the same change; drop test-only public delegations; check scenario-count parity.
- Keep test files within ~3x the production file limit (review hook); split into classes first.
- Never substitute formatter, typecheck, or snapshot evidence for a missing high-risk test; no broad snapshots where a focused assertion explains; never mock the unit under test so the rule cannot fail.
- For a guarantee that matters, add a negative control: inject the violation and confirm the test fails.

## Stop If

- Expected outcome, permission rule, data-loss rule, migration behavior, or error copy is unclear: clarify the source of truth before writing the test.
- A flaky test would pass only by weakening assertions: identify the unstable boundary first.
- Only mocked, placeholder, or happy-path behavior ran: do not mark the behavior verified.

## Verification

- Automated: report command, result, and the boundary it proved. Manual: scenario, environment, action, expected and observed result.
- A test that cannot run: state the skipped command, why, and residual risk.
- Compiler, lint, or typecheck success does not prove behavior, permissions, persistence, UI, or release paths.
