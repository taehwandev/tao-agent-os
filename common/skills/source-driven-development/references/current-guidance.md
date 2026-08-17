---
keyflow_id: sys_source_driven_development
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Source-Driven Development

Use when implementation depends on a framework, SDK, API, platform behavior,
standard, release note, or external documentation that can change over time.

The goal is to avoid coding from stale memory when the correct behavior is
defined by a versioned source.

## Use When

- Adding or changing framework, SDK, package, platform, API, CLI, CI, browser,
  database, or cloud behavior.
- The repo uses a version you have not confirmed.
- A feature depends on current platform rules, deprecations, limits, or release
  notes.
- Existing code and remembered best practice disagree.

For stable local conventions, inspect the repo first. Source-driven work does
not override repo-local instructions or existing architecture without a reason.

## Repository Work-Surface Resolution

Before reading task-specific guidance or editing code, verify the repository
boundary that owns the requested behavior. Request words, a user-supplied path,
path-like text, and dirty Git paths are evidence anchors, not ownership proof.
Only a verified owner path may be promoted through `--surface-path`.

Use a bounded read-only search of at most four evidence hops:

1. extract the most discriminating observable or named anchor;
2. locate its resource, symbol, route, state, producer, or definition;
3. follow direct usages and exclude generated, test-only, and unrelated matches;
4. name the smallest change owner and the nearest check that would fail if the
   owner claim were wrong.

Stop with `resolved`, `ambiguous`, or `not_found`. Only `resolved` permits
task-specific reading and edits. For the other results, report the anchors and
boundaries checked and ask for one behavior-distinguishing clue. Do not restart
the same search indefinitely or ask the user which internal document to read.

A screenshot is a first-class anchor: inspect visible copy, hierarchy, state,
controls, and stable identifiers before asking for a file. Do not persist
sensitive screenshot content in route or gate metadata.

An exact local change may use a one-hop fast path when direct inspection proves
the behavior owner, no competing owner is visible at the nearest boundary, and
a focused falsifying check is known. A named multipurpose or aggregation file
does not qualify merely because the user supplied it.

## Inspect First

1. Repo-local instructions and architecture docs.
2. Manifest, lockfile, wrapper, package, or config that shows the actual
   version.
3. Existing local examples and tests.
4. Official or pinned documentation for that exact version.
5. Changelog or migration notes when changing versions or deprecated APIs.

Use secondary sources only as hints when official or pinned sources are missing.
Do not make them the authority for behavior.

## Decision Rule

Implement the pattern that fits both:

- the repo's actual version and local architecture; and
- the most authoritative available source for the changed API or platform.

When those conflict, prefer repo-local compatibility until a migration decision
is made. Record the conflict and the reason for the chosen path.

## Process

1. Resolve the repository work surface when the change owner is not already
   proven by the fast path.
2. Detect the stack and version from local files.
3. Identify the exact behavior that needs external source confirmation.
4. Read the smallest authoritative source that covers that behavior.
5. Compare the source pattern with nearby code.
6. Implement the smallest compatible change.
7. Verify with a command or scenario that exercises the sourced behavior.
8. Report the source class used, such as repo docs, pinned docs, official docs,
   or migration notes.

## Source Families

When an external source is organized as a family of skills, recipes, examples,
or reference files, do not treat the top-level index or file count as enough.
Create or consult a narrow source map that names:

- the entrypoint for each touched surface
- the implementation-affecting reference group
- the local Tao Agent OS card that owns the reusable rule
- the verification question that proves the source was applied

Keep the source map as a router, not a vendor copy. Distill only recurring
decision rules, stop conditions, and verification requirements into shared
guidance.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "I know this framework." | Confirm the repo version before using version-sensitive APIs. |
| "The blog post has the answer." | Treat it as a hint; find official, pinned, or local source before implementing. |
| "The compiler will catch it." | Compiler success does not prove lifecycle, security, release, or runtime semantics. |
| "The existing code is old, so replace it." | Check compatibility and migration cost before changing local patterns. |

## Red Flags

- The code uses a new API without confirming the installed version.
- A migration guide is relevant but unread.
- A test is updated to match guessed behavior.
- Existing call sites use a different pattern and no compatibility note exists.
- Documentation for one platform or version is applied to another.

## Do Not

- Do not cite memory as the source for volatile platform or SDK behavior.
- Do not mix snippets from different versions without a compatibility note.
- Do not add a dependency or CLI feature before checking existing wrappers and
  package policy.
- Do not browse broad search results when official docs or repo-pinned docs are
  available.
- Do not overfit shared Tao Agent OS guidance to one vendor's API shape.

## Stop If

- The source of truth is unavailable and the behavior affects security, data,
  billing, release, migration, or external state.
- The version cannot be determined and the API differs across versions.
- The sourced approach requires a broader architecture or migration decision
  than the current request allows.

## Verification

Use the narrowest check that proves the sourced behavior: compile/typecheck for
API shape, unit or integration test for semantics, browser/device smoke for
runtime behavior, or release dry run for packaging and CI/CD changes.

For docs-only guidance that cites versioned behavior, verify links and record
the last-verified date when the fact can age.

## Report

Report the detected version or source class, the chosen pattern, the
verification command, and any source/local-code conflict that remains.
