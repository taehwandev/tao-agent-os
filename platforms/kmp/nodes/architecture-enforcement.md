---
keyflow_id: sys_kmp_node_architecture_enforcement
status: review
type: ai-generated
use_when: Adding or changing automated checks for Kotlin module dependency direction, layer imports or naming rules, or fixing a codebase whose documented architecture is not enforced.
skip_when: The change touches no module boundary, layer rule or architecture test.
requires:
  - platforms/kmp/skills/kmp-architecture/references/layering.md
---

# KMP Architecture Enforcement

A layering rule that no test checks will drift. Encode the documented rules
as tests, start from the current state, and ratchet toward the target.

## Rules

- Two checks cover most rules:
  - Module graph: a Gradle-level test or task that reads each module's
    project dependencies and asserts the allowed direction (for example
    `app -> feature -> core`, `core:data -> core:domain -> core:model`, no
    `feature -> feature`, no `core -> feature`).
  - Source rules: a Konsist (or ArchUnit for JVM-only) test module that
    asserts imports and placement, for example feature packages do not import
    `java.io.File`, `ProcessBuilder` or data-layer packages; DI framework
    annotations appear only in the app module; `*UseCase` classes live in the
    domain module; `*StateHolder` classes import no UI toolkit types.
- Start with a baseline: list current violations explicitly in the test (an
  allowlist with one entry per file or edge) so the suite passes on day one.
  New violations fail; fixing one removes its allowlist entry. The allowlist
  only shrinks.
- Each rule names the document it enforces in a comment, so a failing rule
  points the reader to the decision.
- Run the architecture tests in the same CI task as unit tests; they are not
  optional lint.
- Unused declared dependencies are violations too: a module may not declare a
  project dependency it does not import, because it reopens a forbidden path.

## Do Not

- Do not add a new allowlist entry to make a new change pass; fix the change
  or record an explicit architecture decision first.
- Do not encode rules only as review comments or wiki text.
- Do not write a rule so broad that it allowlists most of the codebase; split
  it until the baseline is small and meaningful.

## Verification

- Introduce a deliberate violation locally (for example a feature importing a
  data class) and confirm the test fails with a message naming the rule.
- After a refactor slice, the allowlist diff shows only removals.
