---
keyflow_id: sys_work_surface_resolution_prd
status: stable
type: human-reviewed-needed
---

# Evidence-First Work-Surface Resolution

## Decision

Tao Agent OS should select task-specific guidance only after it has verified the
code boundary that owns the requested change and the behavior that will change.

This is not a new skill, router, or evidence packet. It is a refinement of the
existing request-intent, `--surface-path`, concern, and path-surface routing
flow. The implementation should reduce phrase-driven routing, make path rules
more precise, and require evidence that the selected path is the real owner.

The governing rule is:

> Do not select task-specific documents, read them, or edit the target until the
> change-owning code boundary has been verified from repository evidence.

Repository and runtime instructions that are always required still apply before
this resolution. The rule governs the additional task-specific document set.

## Problem

People often identify a change through observable product evidence rather than
repository vocabulary. A client developer may remember a message, screen,
interaction, screenshot, error, or route without knowing the file, module, or
guidance document that owns it. The efficient human workflow is usually:

1. start from the observable evidence;
2. search the resource, symbol, route, or state that represents it;
3. follow usages to the screen or behavior owner;
4. read the guidance relevant to that owner;
5. make and verify the smallest change.

An agent loses that advantage when it asks the user to name a file or document,
loads broad platform guidance from a word in the prompt, or treats the first
matching path as the owner. The result is unnecessary reading, slow discovery,
wrong-context edits, and unrelated gates.

## Existing Mechanisms

`workflow-doc-surfaces.json` already contains both routing axes that this design
needs:

- `request_intents` promotes documents from normalized request-text patterns.
- `path_surfaces` promotes documents from request paths, explicit
  `--surface-path` values, and dirty Git paths.
- the route already accepts explicit concerns and `--surface-path`.
- Graphify already owns target-project symbol, architecture, and relationship
  queries; Wikimap and the document graph own guidance discovery.

The pre-migration 2026-08-15 repository snapshot contains 38 request-intent
rules. Twenty-three use `request_any`, another twelve use composite
`request_all` patterns, and 18 path-surface rules exist. Nine literal technology
shortcuts are named `*_self_selected`, spanning Android, Application, Flutter,
iOS, KMP, Web, React Native, and Python. Removing all nine leaves 29
request-intent rules: 15 `request_any`, 11 `request_all`, and three rules without
request-text patterns. The 18 path-surface rules remain available for verified
owners.

The important conclusion is not the exact count. Tao Agent OS already has the
dials. The change should turn the existing dials toward verified ownership
instead of adding a parallel `ui-surface-discovery` or
`work-surface-resolution` skill.

## Why Neither Text Nor Path Is Authority

Request text is a weak proxy for implementation ownership. A user saying
“Compose” may describe the technology they see or expect, but it does not prove
which module, entry point, state owner, or verification surface must change.
Literal phrases are therefore useful as test fixtures, not as policy keys.

A path is stronger because it is repository evidence, but it is still a proxy.
A broad file can participate in several concerns. A path rule that maps an
entire multipurpose file to one integration can add irrelevant documents and
gates.

This repository provides a concrete example. A change to request-envelope
fingerprint binding touched `scripts/workflow.py`. The current
`graphify_integration` path surface includes that whole file, so the route added
the `graphify readiness` gate even though the behavior changed request binding,
not Graphify. Moving from text matching to path matching without narrowing the
owner boundary would only replace one kind of false positive with another.

## Required Behavior

### Owner proof is always required

There is no branch where a user-supplied file or framework name skips owner
verification. A named path is a candidate supplied with useful evidence. The
agent must still confirm that it owns the requested behavior rather than merely
referencing, transporting, or aggregating it.

Discovery is one way to obtain owner proof; it is not a separate request type.
An exact request normally makes discovery shorter, not optional.

### Resolve before task-specific document selection

The lifecycle should use this order:

1. apply repository instructions, safety policy, and the minimum deterministic
   workflow contract needed to inspect the repository;
2. derive evidence anchors from the request and supplied artifacts;
3. verify the change owner with bounded, read-only repository inspection;
4. pass only verified owner paths through the existing `--surface-path`
   interface and add evidence-backed concerns;
5. let the existing document router produce the task-specific manifest;
6. read that manifest, edit, and run the nearest falsifying verification.

The output of resolution is the existing route input: verified surface paths
and concerns. No new general-purpose packet is required. If durable evidence is
needed for auditing, extend the existing route or gate evidence rather than
introducing another source of truth.

### Evidence anchors are semantic, not phrase branches

The agent chooses anchors from the meaning and artifacts of the request. Useful
anchors include:

- visible copy, resource identifiers, localization keys, accessibility labels,
  test identifiers, and screenshots;
- symbols, stack frames, compiler errors, log markers, routes, deep links, and
  API paths;
- state transitions, callbacks, event names, serializers, mappers, and config
  keys;
- user-supplied paths, diffs, tests, issue evidence, and design nodes.

These are search strategies, not independent policy routes. Android resource
lookup, React localization lookup, Swift symbol lookup, backend error mapping,
and similar platform techniques are adapters selected after inspecting the
project stack and evidence shape.

### Screenshots are first-class evidence

A screenshot often collapses an ambiguous UI request into deterministic search
anchors. The agent should inspect visible copy, hierarchy, states, controls, and
stable identifiers before asking the user for a file name. It should distinguish
text rendered by the client from remote, generated, or server-provided content,
and it must not persist sensitive screenshot content in route metadata.

Screenshots strengthen the search; they do not prove ownership by themselves.
The extracted anchor still needs a repository evidence chain.

### Owner proof includes a falsification test

The agent must name the closest available check that would fail if its owner
claim were wrong. Examples include:

- a Compose preview, screenshot, or component test for an Android UI owner;
- a Storybook story, component test, or visual regression for a React owner;
- a focused unit test for a state reducer, mapper, formatter, or resource
  resolver;
- a route or integration test when ownership spans a deliberate contract.

If no such check can be identified, the owner claim is weak. The agent must
gather more evidence, reduce confidence, or ask the smallest question that
distinguishes the remaining candidates.

## Bounded Search Contract

Owner resolution must terminate. The default search is read-only and progresses
through at most four evidence hops:

1. **Anchor:** extract the most discriminating observable or named identifier.
2. **Definition:** locate the resource, symbol, route, state, or producer.
3. **Usages:** follow direct consumers and filter generated, test-only, and
   unrelated matches.
4. **Owner and check:** identify the smallest boundary that changes the behavior
   and the nearest falsifying verification.

Within a hop, the agent may compare several candidates, but it should not restart
the same search with synonyms indefinitely. It stops with one of three results:

- **resolved:** one owner is supported by an anchor-to-owner chain and a nearby
  falsifying check;
- **ambiguous:** two or more plausible owners remain and the repository cannot
  distinguish the requested behavior;
- **not found:** the bounded search found no repository-owned chain, including
  the possibility that content is remote, generated, or absent from the
  checkout.

For `ambiguous` or `not found`, report the anchors and boundaries checked, then
ask for one new observable clue. Do not ask the user which internal document to
read. Good questions distinguish behavior, such as which of two screens is
shown or whether the content comes from the server.

## Applicability and Cost Control

Owner resolution must not become a ceremony attached to every edit.

The proof is already satisfied when all of the following hold:

- the requested behavior and bounded owner are explicit;
- the named path is directly inspected and contains that behavior;
- no competing owner or indirection is visible at the nearest call or usage
  boundary;
- a focused verification for that owner is known.

This fast path covers typo fixes, exact documentation link repairs, a focused
test expectation update, and similarly local changes. It still performs owner
verification, but the proof can be a single inspection rather than a multi-hop
search.

Full bounded discovery is required when the request starts from observable UI,
the named file is an aggregator or shared entry point, several usages exist,
the content may be remote or generated, or path rules would add materially
different documents or gates.

## Routing Changes

Implementation should evolve the existing configuration and router in this
order:

1. classify each `request_intents` rule as semantic intent, provisional
   technology hint, or literal phrase shortcut;
2. remove every literal technology shortcut from required-document promotion;
   no `*_self_selected` exception remains for a client or server framework;
3. preserve expressions as paraphrase and negative test cases rather than
   production routing keys;
4. split broad `path_surfaces` so multipurpose orchestration files do not imply
   every concern implemented somewhere in the file;
5. prefer smaller owner paths, symbols, or evidence-backed concerns over whole
   orchestrator files;
6. route dirty paths as candidates until their relation to the requested change
   is verified;
7. feed verified paths through the existing `--surface-path` contract and use
   the resulting manifest as the only task-specific guidance source.

The Graphify false positive is the first required regression case:
request-envelope work in `scripts/workflow.py` must not add Graphify guidance or
the `graphify readiness` gate unless the changed owner actually belongs to the
Graphify integration.

## Scope

### In scope

- refining request-intent and path-surface routing policy;
- defining owner proof, bounded search, and stop conditions;
- using screenshots and other observable evidence as first-class anchors;
- distinguishing candidate paths from verified owner paths;
- selecting task documents from verified `--surface-path` and concern inputs;
- regression tests for paraphrases, false positives, ambiguity, and fast paths.

### Out of scope

- adding a new skill bundle or independent owner-resolution subsystem;
- creating a new general-purpose evidence packet;
- replacing Graphify, Wikimap, the document graph, or the route manifest;
- encoding platform-specific prompt phrases as durable policy;
- publishing the later blog post before the design is implemented and verified.

## Acceptance Criteria

1. Given a literal framework phrase on any supported client or server stack,
   including React Native, Expo, Python, and FastAPI, when routing runs before
   owner proof, then no `*_self_selected` rule promotes task-specific guidance;
   paraphrases with the same observable behavior produce the same candidates.
2. Given a user-supplied path, when the path does not own the requested behavior,
   then the agent follows or rejects it rather than treating it as authority.
3. Given a visible UI message or screenshot, when the content is repository
   owned, then the agent can trace an anchor through its definition and usages
   to the smallest change owner before selecting task-specific documents.
4. Given shared or reused content, when multiple owners remain plausible after
   four evidence hops, then the agent reports `ambiguous` and asks one
   behavior-distinguishing question.
5. Given remote, generated, or absent content, when no repository chain is found
   within the search contract, then the agent reports `not found` without an
   unbounded retry loop.
6. Given a verified owner, when routing continues, then the existing
   `--surface-path` and concern inputs determine the task-specific document
   manifest; no parallel packet or skill is required.
7. Given an owner claim, when the agent cannot name the nearest check that would
   fail if the claim were wrong, then the claim is not accepted as resolved.
8. Given an exact, local, low-risk change, when one direct inspection proves the
   owner and verification, then no multi-hop discovery ceremony is required.
9. Given request-envelope binding work in `scripts/workflow.py`, when route
   surfaces are inferred, then Graphify guidance and readiness are absent unless
   the actual changed owner is part of the Graphify integration.
10. Given phrase examples in tests, when production routing changes, then those
    examples remain behavioral fixtures and are not copied into new policy
    branches.
11. Given a semantic request with multiple behavior or boundary signals, or a
    verified owner path, when routing continues, then the matching intent or
    path surface still promotes its guidance without restoring a literal
    framework shortcut.

## Verification Matrix

| Scenario | Evidence chain | Nearest falsifying check | Expected result |
| --- | --- | --- | --- |
| Android visible message | screenshot or copy -> resource key -> usages -> screen owner | preview, screenshot, or component test | resolved or ambiguous |
| React localized copy | screenshot or copy -> locale key -> component usage | story, component test, or visual regression | resolved or ambiguous |
| Exact source path | supplied path -> inspected behavior -> caller/usage boundary | focused owner test | resolved fast path or redirected owner |
| Shared orchestration file | touched function -> responsibility -> actual integration owner | focused routing regression | no unrelated concern gate |
| Server-provided error | visible message -> response/model mapping -> presentation owner | mapper or integration test | resolved or not found |
| Missing checkout evidence | anchor -> bounded definitions/usages searched | none available | not found, one minimal question |

## Implementation Decisions

The colocated `spec.md` resolves the technical choices:

- verified ownership extends the existing gate ledger;
- `--surface-path` contains only verified owner paths;
- request and dirty paths stay visible as route `surface_candidates`;
- code routes use a fixed one-to-four-hop budget;
- screenshots are evidence anchors and sensitive visual content is not stored;
- literal technology shortcuts are removed across client and server stacks while
  semantic request intents
  and verified path surfaces remain;
- Graphify route behavior has a purpose-named owner instead of multipurpose
  workflow entrypoints.

## Delivery Sequence

1. Audit `request_intents` and `path_surfaces` by owner precision and current
   false-positive coverage.
2. Write the technical spec for evidence representation, route refinement, and
   migration compatibility.
3. Add failing regression tests, beginning with the unrelated Graphify gate.
4. Narrow the existing rules and connect verified owner paths to the existing
   route inputs.
5. Validate Android, Web, exact-path, shared-file, ambiguous, not-found, and
   screenshot-led scenarios.
6. Update the public explanation only after implementation evidence can
   distinguish proposed behavior from shipped behavior.

## Blog Source Notes

The later article should begin with the human behavior: “I remember the screen,
not the file.” Its main example should trace visible copy or a screenshot to a
resource, usage, owner, and falsifying check. The central correction is that
neither prompt words nor file paths are ownership; both are clues.

The article should explain that the practical improvement was not a new AI
subsystem. Tao Agent OS already had request-intent and path-surface routing. The
work was to reduce phrase-driven policy, narrow broad path proxies, and place
verified ownership before task-specific reading. Phrase lists belong in the
test corpus, and a bounded stop condition is what keeps “minimal reading” from
turning into endless search.

The implementation is now shipped in the local source: code routes enforce the
owner-resolution gate, request and dirty paths remain candidates, verified
paths retain routing authority, all literal technology shortcuts are removed,
and the focused plus full workflow test suites pass. The article may describe
the capability as implemented while keeping repository release or deployment
claims separate.
