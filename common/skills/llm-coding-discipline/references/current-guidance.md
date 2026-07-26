---
keyflow_id: sys_llm_coding_discipline
status: stable
type: human-reviewed-needed
---

# LLM Coding Discipline

Use before coding. These rules reduce common LLM mistakes. Bias toward caution over speed; use judgment for trivial tasks.

## Think First

- State assumptions when they affect implementation.
- If multiple interpretations exist, surface them.
- Ask when ambiguity changes the result.
- Push back on unnecessary scope or complexity.

## Keep It Simple

- Build only what was asked.
- No speculative features, config, flexibility, or abstractions.
- No single-use abstraction.
- If the solution feels much larger than the problem, simplify.

## Match Structure To The Problem (Hard Stop)

The most expensive LLM failure is turning a small task into a sprawling
multi-file design: new interfaces, adapters, factories, managers, config, layers,
and directories for a change that needed a few edited lines. This is not
thoroughness. It burns tokens, inflates analysis and review time, and leaves
code that is harder to change than the problem ever required. Treat it as a
defect, not diligence.

Default to changing existing code in place. A simple task is a small diff to
files that already exist — ideally one — not a new subsystem. Find where the
behavior belongs in the current structure and put it there.

Before creating ANY of the following, stop and name in one sentence the concrete
risk that exists right now and that this construct protects. If you cannot, do
not create it:

- a new file, module, package, or directory
- a new interface, abstract class, protocol, or generic type parameter
- a new layer, adapter, factory, builder, manager, service, or wrapper
- a new config option, flag, options object, or indirection between a caller and
  the behavior it calls
- a new dependency

"It might help later," "it is more flexible," "it is cleaner," and "best
practice" are not concrete present risks. Valid reasons are a second real caller
that exists now, a test seam a real test needs now, a platform or security
boundary this change actually crosses, or an owner boundary the repo already
enforces.

Proportionality gate, run before writing code:

```text
1. Restate the task in one sentence.
2. Locate where it belongs in the EXISTING files.
3. Write the smallest diff that makes it correct there.
4. Count new files and new abstractions. For a simple task the expected answer
   is zero new abstractions and zero or one new file.
```

If your plan exceeds that, stop and collapse it before writing — do not explore
the sprawling version first. When new structure is genuinely required, state the
one-line reason, then add only the structure that reason justifies, never the
surrounding scaffold you imagine it will later need.

## Avoid Boilerplate

Boilerplate is code that adds lines without adding meaning. LLMs emit it by
reflex — ceremony, scaffolding, and hand-rolled equivalents of idioms that
already exist. Even a one-line change can arrive buried in it. Before writing a
unit, ask whether a senior engineer in this repo would write this much code for
this task. If not, cut the ceremony. This is a distinct failure from an
oversized unit (see Do Not Pack Everything Together): a short function can still
be pure boilerplate.

- Reach for the language, standard library, and framework idiom before writing
  it by hand. Prefer map/filter/comprehension, destructuring, literals, built-in
  collection and string operations, and framework helpers over manual loops,
  index bookkeeping, and re-implemented equivalents.
- Do not wrap trivial logic in a class, manager, service, factory, or builder
  when a plain function, value, or literal says the same thing. Introduce a type
  only when it carries state, identity, or a caller contract.
- Do not add defensive scaffolding the code cannot reach: `try/catch` that only
  rethrows, null checks the type system already guarantees, validation of inputs
  that cannot be invalid, or re-checking a condition the caller already enforced.
- Do not restate the obvious: no redundant intermediate variables, no
  pass-through wrappers, no getters/setters over fields the language already
  exposes, no DTO/model mapping layer when one shape already works.
- Do not add an interface, options object, generic parameter, callback, or hook
  for a single current caller "in case" it is needed later. Add the seam when
  the second real caller exists.
- Collapse copy-pasted structural repetition into a loop, table, or data-driven
  form only when the cases are truly identical; keep them inline when they differ
  in ways flags or knobs would have to hide.
- Do not narrate the code in comments. Keep comments for why, risk, contract, or
  non-obvious constraints.
- Handle each failure at the layer that can act on it. Do not log-and-rethrow the
  same error at every level.

The test for a line is whether a reader needs it to understand or run the
behavior. If removing it loses no information a reader needs and changes nothing
a caller can observe, it is boilerplate — leave it out.

## Use SOLID As The Coding Baseline

- Write production code against SOLID responsibility and dependency rules.
- Treat Interface Segregation as mandatory for caller-facing contracts: callers
  should not depend on operations, props, callbacks, lifecycle hooks, SDK
  details, or implementation dependencies they do not use.
- Apply Dependency Inversion when product rules, state transitions, adapters,
  or platform/external systems need focused tests or import isolation.
- Do not add layers, inheritance, dependency injection containers, or abstract
  factories only to satisfy an acronym.
- Use DDD only when real domain pressure exists; start with a smaller use case,
  policy, mapper, reducer, or state owner when the rules are still local.

For detailed checks, use `common/skills/solid-design-principles/SKILL.md`.

## Do Not Pack Everything Together

- Do not solve implementation speed by dumping unrelated code into one file.
- Do not write one large function, component, hook, handler, job, or script step
  that owns parsing, validation, IO, state changes, rendering, and recovery.
- Do not add new behavior to an oversized unit without first naming the
  responsibility being added and choosing the nearest useful split.
- Do not create helper functions or files that are not reusable, testable, or
  reviewable. A helper must have a clear responsibility; otherwise keep the
  logic inline or file-private.
- Do not create generic architecture folders before the code has a real owner,
  caller contract, or dependency boundary.

## Change Surgically

- Touch only lines tied to the request.
- Match existing style.
- Do not refactor adjacent code unless required.
- When an existing file already exceeds an owner-count budget, keep the review gate ratcheted to structural growth. A one-for-one owner rename with no count or role expansion does not require splitting unrelated legacy owners.
- Remove only unused code created by your change.
- Mention unrelated dead code; do not delete it.

## Verify The Goal

Turn work into one to three concrete checks before or during the change:

```text
1. User request -> observable outcome -> verification evidence.
2. Risk touched -> guardrail or regression check -> verification evidence.
```

Examples:

- README install guidance changed -> links and commands still resolve -> run
  markdown link/path check or document why it cannot run.
- Login error behavior changed -> invalid login shows the expected error and
  valid login still works -> run the focused test or manual path.
- Refactor without intended behavior change -> public behavior stays equivalent
  -> run the existing narrow test or compare before/after behavior.

If success cannot be verified, name the gap before proceeding.
