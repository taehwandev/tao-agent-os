---
keyflow_id: sys_android_feature_package_structure
status: review
type: human-reviewed-needed
---

# Android Feature Package Structure

Use when deciding whether a feature flow needs additional packages or when
auditing an existing package layout. This card complements module and file
ownership guidance; it does not prescribe a repository-wide directory tree.

## Three-Step Gate

1. **Flow root** — identify the smallest package that owns the user-visible
   flow, its state, and its immediate collaborators.
2. **Candidate classification** — propose a package only when it represents a
   stable owner, dependency boundary, or independently testable responsibility.
   Classify the flow as compact or complex; compact flows usually stay together.
3. **Audit and collapse** — check callers, imports, visibility, and test seams.
   Collapse a split that only groups types or creates empty indirection.

Do not create default `model/`, `ui/`, `mapper/`, `di/`, or other type-based
packages without an ownership or boundary reason. A package boundary note
should state the owner, allowed callers, dependency direction, and the evidence
that keeps the split useful.

## Flow-Internal Owner Taxonomy

Before adding subpackages, classify flow files into these owner layers, in
order. If this classification is not settled, do not add subpackages.

1. **Platform/entry owner** — Activity/route hosts, launch and intent-argument
   mapping, activity results, permissions, and background-work bridges. This
   layer keeps render code from parsing raw intents or results.
2. **Render owner** — screen and components: rendering and local interaction
   holders only. No repositories, route dispatch, or platform parsers.
3. **State-owner runtime** — the ViewModel and user-flow-unit transitions. The
   action dispatch `when` stays in the ViewModel file; only per-flow-unit
   transition handling moves out.
4. **Flow contract/model owner** — `UiState`, `Action`, `Effect`, and small
   flow-closed drafts. The default location is the flow root; do not create
   `contract/` or `state/` packages just to collect internal UDF types.
5. **Pure policy owner** — side-effect-free, testable product rules such as
   step progression or submit eligibility. State mutation, UI, and effect
   execution never move here.

Mappers earn a package only when a layer-boundary conversion is an independent
test target; launch-argument and result parsing belong to the platform/entry
owner, never to a mapper package.

## Product Terms Are Not Boundaries

Product state names and new API names or endpoints (draft, pending, preview,
re-entry) are not evidence for a sibling flow package, screen, or state-holder
family. Before creating a sibling flow, compare it with the nearest existing
flow across render, action, state/lifecycle, side-effect/navigation,
failure/retry, and test responsibilities; create the sibling only when it is
an independently changing owner on those axes. When only the entry input, an
identifier's presence, preconditions, or the first transition differ and the
subsequent screen and interactions match, reuse the existing owner and isolate
the difference as the smallest state, mode, or entry-orchestration delta. Do
not replicate the same UI and interaction into a sibling flow to dodge a
dependency direction.

## Boundary Promotion Ladder

Choose the first boundary that satisfies the need:

```text
private file -> flow package -> feature-local owner -> feature module
-> public UI/module boundary -> shared capability
```

Promote code to a feature module or shared capability only when the smaller
boundary cannot satisfy a real caller, release, dependency, or test boundary.
Shared promotion requires at least two stable callers plus a common contract,
clear owner, and preserved dependency direction; reuse by itself is not enough.

## Verification

- Every new package has a named owner and at least one concrete boundary or
  caller.
- Compact flows do not gain ceremony without a measurable benefit.
- Complex flows preserve dependency direction and expose a focused test seam.
- The boundary note and the nearest package/module verification are updated in
  the same change.
- A new sibling flow records its concrete behavioral difference and independent
  owner responsibilities, and no parallel component family implements the same
  render and actions after the first transition.
