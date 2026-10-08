---
keyflow_id: sys_android_compose_performance
status: review
type: human-reviewed-needed
requires:
  - platforms/compose/nodes/ui-performance.md
---

# Compose Performance And Stability

Read when a task reports or measures jank, excess recomposition, stability
problems, slow lazy-list scrolling, startup cost, or another Compose
performance regression. This file is the Android measure-first diagnosis
procedure.

The authoring rules every composable follows by default (modifier order,
deferred reads, lazy `key`/`contentType`, `Modifier.Node`, animation API
choice, effect keys, `rememberUpdatedState`) are in
[Authoring Rules](current-guidance.md#authoring-rules), not here. The
measurement-independent triage, fixes and strong-skipping rules are in
`platforms/compose/nodes/ui-performance.md`.

## Compose Performance Gate

Use a measure-first loop for Compose performance work:

```text
Measure -> Diagnose -> Fix one cause -> Verify
```

Do not call a change a performance fix only because it adds packages,
annotations, `remember`, module splits, or a different architecture pattern.
Record the bottleneck category first: recomposition, stability, lazy layout,
main-thread work, startup, allocation, subcomposition, side effects, tracing,
or release configuration.

Performance claims should use release-like evidence whenever practical:

- Measure Compose runtime behavior in a release or benchmark variant with R8
  enabled and a physical device when the claim is about frame time, jank,
  startup, or scroll smoothness. Debug builds, emulators, and Layout Inspector
  counts are diagnostic only unless the report says so.
- Quote the variant, device, compilation mode, iteration count, and before/after
  numbers when reporting a measured improvement.
- Use compiler reports, Layout Inspector, recomposition tracing,
  Macrobenchmark, Baseline Profiles, Perfetto, or focused manual evidence
  according to the repo's tooling. Do not invent metrics.
- Keep each fix scoped to one diagnosed cause and remeasure before moving to the
  next optimization; triage order and the fix catalogue are in the node.

## Stability And Strong Skipping

Compose performance starts with stable inputs. Stability annotations are contracts.
The annotation table and immutable-collection rules are in
`platforms/compose/nodes/state-model-stability.md`; strong-skipping and
escape-hatch rules in `platforms/compose/nodes/ui-performance.md`.

## Advanced Stability Options

Use compiler and Gradle-level stability tools only after diagnosing a real
recomposition or performance issue:

- A Compose stability configuration file can mark external or standard-library
  types as stable, but it is a codebase-wide contract. Add entries only for
  types whose immutability and equality behavior the project can defend.
- Do not change compiler stability policy, add stability configuration, or move
  state across component boundaries without measurement or a concrete
  recomposition/jank reproduction.
- Do not use suspected performance as the reason to migrate a View screen to
  Compose, or a Compose screen back to View. Treat framework migration as a
  separate architecture task with its own evidence.

## Report

- Bottleneck category, user-visible path, and the measurement tool used.
- Variant, device, compilation mode, iterations, and before/after numbers, or
  an explicit note that the evidence is diagnostic only.
- The one cause fixed per iteration and the remeasurement after it.
