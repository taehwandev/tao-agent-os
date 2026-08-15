---
keyflow_id: sys_work_surface_resolution_spec
status: stable
type: human-reviewed-needed
---

# Work-Surface Resolution Technical Specification

## Scope

This specification implements the contract in `docs/work-surface-resolution/prd.md`
without adding a skill, router subsystem, or general evidence packet. It extends
the existing route manifest and gate ledger, and it keeps `--surface-path` as the
only path input that may promote task-specific path guidance.

## Ownership

The implementation has four existing owners:

- `workflow-doc-surfaces.json` owns semantic request hints and path-to-guidance
  mappings.
- `scripts/workflow_doc_surfaces.py` owns document-surface matching.
- `scripts/workflow_gate_policy.py` owns when code routes require owner proof.
- the existing gate-evidence and finish-validation modules own durable proof and
  completion rejection.

Graphify route readiness is extracted to a purpose-named route policy module so
that multipurpose workflow entrypoints no longer act as Graphify owners.

## Route Inputs

`--surface-path` means a verified change owner. It is not a user-supplied hint
and it is not a dirty Git path. A caller may repeat it for a deliberate
cross-owner contract.

Request path references and dirty Git paths remain useful candidates. Preflight
records them in the route as `surface_candidates`, separated by source, but it
does not pass them to document-surface matching. This keeps the clues visible
without granting them routing authority.

Request-intent rules remain available for semantic workflow intent. Every
literal technology shortcut named `*_self_selected` is removed across Android,
Application, Flutter, iOS, KMP, Web, React Native, and Python. The phrases
remain regression fixtures.

The migration intentionally deletes all nine request-policy rules, reducing the
38-rule baseline to 29 request-intent rules and its 35 text-pattern rules to 26:

- `android_compose_self_selected`;
- `application_react_self_selected`;
- `flutter_widget_self_selected`;
- `ios_swiftui_self_selected`;
- `ios_uikit_self_selected`;
- `kmp_compose_self_selected`;
- `web_react_self_selected`;
- `react_native_self_selected`;
- `python_web_service_self_selected`.

They are no longer needed because a framework word cannot prove ownership.
The rule is uniform across client and server technologies: adding a nearby
generic word such as `screen`, `API`, or `endpoint` does not turn a framework
choice into owner proof. Semantic multi-signal contracts such as a combined
React Native and Python web service or an explicit React Native Android-native
boundary remain available as candidates, and verified owners still select
guidance through path surfaces.

## Gate Contract

Code-work routes require `work surface resolution` before `source docs` and
before implementation. The gate uses the existing structured ledger fields:

- `result`: `resolved` for a successful gate;
- `owner`: the smallest boundary that changes the requested behavior;
- `anchors`: observable evidence or explicitly supplied identifiers;
- `evidence`: the repository chain from anchor to owner;
- `surface_paths`: verified owner paths passed or ready to pass through
  `--surface-path`;
- `concerns`: evidence-backed route concerns, or an explicit `none`;
- `search_hops`: an integer from one through four;
- `verification`: the nearest check that would fail if the owner claim were
  wrong.

The validator rejects `ambiguous`, `not_found`, zero or more than four hops,
missing chain links, missing owner paths, and absent falsifying verification.
An exact local change uses the same contract with `search_hops=1`.

`ambiguous` and `not_found` are terminal failed-gate results. The agent reports
the anchors and boundaries checked, asks for one behavior-distinguishing clue,
and does not read task-specific guidance or edit the target.

## Screenshot Boundary

A screenshot is an `anchors` value, not a new routing branch. Visible copy,
hierarchy, state, control labels, and stable identifiers may seed the bounded
search. Private image contents are not persisted in route metadata; evidence
records use only a safe description or stable repository identifier.

## Graphify Precision

Graphify readiness is selected by an explicit `graphify` concern, the semantic
Graphify request rule, or verified paths owned by Graphify integration. The
`graphify_integration` path surface includes purpose-named Graphify setup,
inspection, documentation, and route-policy owners. It does not include
`scripts/workflow.py`, the whole document-surface map, or another multipurpose
workflow entrypoint.

## Compatibility

- Existing explicit `--surface-path` callers continue to receive path-surface
  guidance.
- Request and Git-status path extraction helpers remain available for candidate
  discovery and tests.
- Semantic request-intent rules and natural-language document search remain
  candidate sources.
- No route packet, execution capsule, or hook status schema changes.

## Verification

Focused tests must prove:

1. phrase-only framework requests, including React Native, Expo, Python, and
   FastAPI variants, do not match any self-selected rule;
2. request path references and dirty paths are candidates, not promoted paths;
3. explicit verified paths still promote matching guidance;
4. semantic multi-signal request intents still promote their contract guidance;
5. `scripts/workflow.py` does not add Graphify readiness;
6. a purpose-named Graphify owner still adds readiness;
7. code routes require owner proof before source docs;
8. only a resolved one-to-four-hop evidence chain with a nearest falsifying
   check passes the finish validator.
