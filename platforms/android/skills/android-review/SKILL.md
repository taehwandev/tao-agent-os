---
keyflow_id: sys_platforms_android_android_review_md_skill
status: review
type: ai-generated
---

# Android Review

This card owns how an Android change is reviewed: which surface procedures to
run, how each finding is written, and what evidence a change needs before it
can be accepted as complete.

## Steps

1. **Anchor to the requirement and size.** Before reading the diff for issues,
   apply the proportionality gate in
   [llm-coding-discipline](../../../../common/skills/llm-coding-discipline/references/current-guidance.md)
   and the reviewable-unit rules in
   [change-size-policy](../../../../common/skills/change-size-policy/SKILL.md).
   Write down the requirement the change serves; every finding is measured
   against it.
2. **Read the review reference.** For every Android review you MUST read
   [current-guidance.md](references/current-guidance.md) before writing
   findings.
3. **Classify the changed surfaces** and run each matching procedure. Each
   procedure is mandatory when its surface is in the diff:

   | Changed surface | Run |
   | --- | --- |
   | Resource, listener, effect, Flow collection, coroutine scope | [android-memory-lifecycle](../android-memory-lifecycle/SKILL.md) Steps |
   | Main thread, IO, startup, cache, network, media, dependency | [runtime-performance.md](references/runtime-performance.md) classification and rules |
   | Composable performance, recomposition, lazy lists | [compose-performance.md](../android-compose-ui/references/compose-performance.md) |
   | ViewModel, `UiState`, effects, repository boundary | [android-viewmodel-state](../android-viewmodel-state/SKILL.md) |
   | Module, package, `api`/`impl`, build logic | [android-module-structure](../android-module-structure/SKILL.md) |
   | Worker, foreground service, sync, upload | [android-background-work](../android-background-work/SKILL.md) |
   | Manifest, intent, deep link, WebView, storage, credentials | [android-security](../android-security/SKILL.md) |
   | Platform SDK named in the source trigger map | [external source coverage](../android-external-skill-source-coverage/references/current-guidance.md) |

4. **Write each finding** in the
   [Finding Format](references/current-guidance.md#finding-format):
   requirement, risk, failure scenario, fix direction. Drop findings based on
   taste, speculative future extensibility, or refactors outside the
   requirement.
5. **Apply the completion gate.** If the change touches external state or
   persisted data, apply
   [Completion Gate](references/current-guidance.md#completion-gate-external-state-and-persisted-data).
   A compile or unit-test pass alone does not accept it.
6. **Choose the verification** from
   [Tools](references/current-guidance.md#tools), narrowest first.

## Source Map

| Need | Source |
| --- | --- |
| Review checklist, finding format, completion gate, tools | [current-guidance.md](references/current-guidance.md) |
| Runtime performance procedure | [runtime-performance.md](references/runtime-performance.md) |
| Generic review workflow | [code-review](../../../../common/skills/code-review/SKILL.md) |
| Measurement proof rules | [performance-verification](../../../../common/skills/performance-verification/SKILL.md) |

## Do Not

- Do not report a finding without a concrete failure scenario grounded in the
  changed lines.
- Do not accept a performance change without reproduction or measurement
  evidence, or a lifecycle change on compile success.
- Do not let package or owner-count mechanics crowd out lifecycle, state,
  performance, and security findings.

## Stop If

- The requirement the change serves is unknown. Ask for it instead of
  reviewing against taste.
- A surface procedure in step 3 applies but its card cannot be loaded. Report
  the gap.

## Verification

Each surface procedure you ran is named in the report with the evidence it
produced. Unverified paths are listed as remaining manual checks, not as passed.

## Report

Findings first, most severe first, in the finding format. Then the surface
procedures run, the verified paths, and the remaining manual checks and
residual risk.

Route or frontmatter maintenance: validate links and keep this entrypoint
selected by the route.
