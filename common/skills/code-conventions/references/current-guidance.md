---
keyflow_id: sys_code_conventions
status: stable
type: human-reviewed-needed
---

# Code Conventions

Use when writing, changing, or reviewing code style, naming, structure,
comments, errors, and formatting.

Repo-local conventions, formatter, linter, and language idioms win over this
common baseline.

For app, repo, package, module, CLI, service, slug, or bundle-id naming, also
use `common/skills/project-naming/SKILL.md`.

For SOLID, Interface Segregation, Dependency Inversion, and DDD/domain-modeling
fit, also use `common/skills/solid-design-principles/SKILL.md`.

For file/module ownership, public contract, package layout, or `api`/`impl`
split decisions, also use
`../../code-structure-ownership/references/current-guidance.md`.

For code that is being extracted, moved into shared modules, reused by multiple
callers, or promoted to a package/API, also use
`common/skills/reusable-code-design/SKILL.md`.

For reusable component-like APIs, callbacks, slots, and controlled state, also
use `common/skills/component-api-design/SKILL.md`. For state shape, source of truth, async
states, and one-off effects, use `common/skills/state-modeling/SKILL.md`. For typed failures
and retry/recovery behavior, use `common/skills/error-modeling/SKILL.md`.

## Priority

1. Repo-local formatter, linter, compiler, and framework rules.
2. Existing local patterns in the touched area.
3. Language and platform idioms.
4. This shared baseline.

## Strict Static Quality Profile

Use this profile when a repo has no stricter local formatter, linter, or static
analysis policy. Repo-local tool configuration still wins, but do not use a
missing config as permission to write loose code. Treat these as review
defaults and CI candidates for new projects:

| Concern | Strict Baseline |
| --- | --- |
| Formatter ownership | Formatting belongs to the repo formatter. Do not hand-align code against the formatter or reformat unrelated files. |
| Line length | Prefer 100-120 columns for readable code. Treat 160 columns as a hard maximum for source code unless the language formatter or repo-local config sets a lower limit. Do not use long lines to hide complex expressions. |
| Wrapping | When a call, declaration, generic clause, builder, modifier chain, SQL/query builder, or object literal wraps, use one argument/property per line and a trailing comma where the language/tool supports it. |
| Naming | Types and modules are nouns or capability names. Functions and commands are verbs or verb phrases. Boolean values read as predicates. Avoid vague names such as `manager`, `helper`, `util`, `data`, `temp`, `doStuff`, or caller-specific abbreviations. |
| Parameters | Keep public functions and components to about five parameters or fewer. Prefer a typed request/options object only when the fields are a real caller-facing contract, not a dumping bag. |
| Complexity | Keep cyclomatic/cognitive complexity low enough that one branch can be reviewed in one pass. More than about 10 decision points, nested depth over 3, or several unrelated branches is split pressure. |
| Function size | Apply the unit-size gates in `../../code-structure-ownership/references/current-guidance.md`; local policy wins when stricter or explicitly different. |
| File ownership | Apply the file ownership and size gates in `../../code-structure-ownership/references/current-guidance.md`; local policy wins when stricter or explicitly different. |
| Imports | Imports are formatter-sorted and boundary-safe. Do not use wildcard imports, deep implementation imports, or barrel/index imports that hide forbidden dependencies unless the repo documents that pattern. |
| Suppressions | Lint suppressions, `// swiftlint:disable`, `@Suppress`, `eslint-disable`, `# noqa`, or equivalent require a short reason and the narrowest scope. Do not suppress file-wide to make new code pass. |

Language/tool defaults for strict review:

| Stack | Formatter | Linter/static analysis | Extra checks |
| --- | --- | --- | --- |
| Android/Kotlin | `ktlint` or `ktfmt` | `detekt`, Android Lint | Compose compiler/stability checks when Compose state or performance changed. |
| KMP/Kotlin server | `ktlint` or `ktfmt` | `detekt` | Dependency direction and source-set boundary checks when modules move. |
| Swift/iOS/macOS | `swift-format` or SwiftFormat | SwiftLint, Swift compiler warnings | `Sendable`, actor isolation, access control, target membership, and package boundary checks. |
| Web/TypeScript | Prettier | ESLint, TypeScript compiler, framework lint | Import-boundary lint, hooks rules, accessibility lint, and route/build checks when available. |
| Python/server scripts | Ruff formatter or Black | Ruff lint, mypy or pyright when typed | Import cycles, typed public APIs, async/resource cleanup, and packaging checks. |
| Go | `gofmt` / `goimports` | `go vet`, staticcheck when configured | Race, context cancellation, and error wrapping checks for concurrent or server code. |
| Rust | `rustfmt` | Clippy | Ownership/lifetime, error handling, feature flag, and unsafe-boundary checks. |

For existing repos, first discover the local commands and config files:
`detekt.yml`, `.editorconfig`, `.swiftlint.yml`, `.swift-format`, `.eslintrc`,
`eslint.config.*`, `prettier.config.*`, `pyproject.toml`, `ruff.toml`,
`mypy.ini`, `tsconfig.json`, `go.mod`, `Cargo.toml`, or the repo's wrapper
scripts. If a tool is configured, run it or explain why it was not run. If no
tool is configured, apply the strict baseline in review and document the gap
instead of inventing a one-off style.

## Rules

- Make code easy to delete, move, and test.
- Use SOLID as the default design baseline for production code, while avoiding
  layers or abstractions that do not protect a real responsibility, caller
  contract, test boundary, or dependency edge.
- Keep caller-facing contracts narrow. Do not make a caller depend on a broad
  service, repository, context, component prop object, hook return type, SDK
  client, or module export when it needs only a role-sized subset.
- For Kotlin, do not introduce `typealias`. Kotlin aliases are alternative
  names for existing types, not new types, so they are poor contracts for
  domain identifiers, callbacks, platform types, or import boundaries. Use
  named value classes, interfaces/fun interfaces, data classes, or explicit
  types when a concept needs a name.
- Do not transfer the Kotlin `typealias` rule to Swift. Swift type aliases are
  useful when they intentionally clarify a package/public API, protocol
  associated type, or long generic shape. Still use a real Swift type when the
  code needs identity, invariants, access-controlled storage, validation, or
  security-sensitive separation.
- Never write a fully qualified name inline in the code body to avoid adding
  an import. Add the import and use the short name. On a simple-name collision
  use an alias import, not an inline qualified name. An edit tool that failed
  to modify the import block is not an exemption — fix the imports.
- In adapters, decorators, and facades, name the wrapped or delegated
  dependency after the role of the wrapped type, never after the wrapping
  relationship. Do not name the field or parameter `real`, `impl`, `delegate`,
  `wrapped`, `wrapper`, `target`, `origin`, or `inner`; a parameter delegating
  to a user repository is `userRepository`, not `real`.
- Treat module public exports as interfaces. A module should expose a narrow
  contract for its consumers instead of forcing them to import implementation,
  platform, SDK, fixture, or unrelated feature details.
- Treat reuse as an ownership boundary. Extract shared code only when the caller
  contract is clear enough to make future changes easier.
- Prefer clear names over comments that explain unclear names.
- Keep each function, component, class, hook, or service focused on one reason to change.
- Keep UI, state, domain, data, and platform concerns separated at the nearest useful boundary.
- Pick the smallest structure that protects a real boundary; do not create a
  package or module only to mirror a preferred architecture.
- Do not add a new abstraction for one call site unless it protects a risky boundary.
- Do not scatter booleans for roles, permissions, entitlements, loading, or error states when a typed state or policy object would make behavior clearer.
- Prefer typed errors, result objects, or framework error types over string matching.
- Avoid hidden global state, implicit environment behavior, and hard-coded production data.
- Keep user-facing copy out of low-level logic when the repo has i18n or copy ownership.
- Comments should explain why, risk, contract, or non-obvious constraints. Do not narrate obvious code.

## Do Not Ship Monoliths

This document keeps convention-level guidance. The canonical split criteria for
functions, files, classes, packages, modules, CSS, and shared code live in
`../../code-structure-ownership/references/current-guidance.md`; use that file
for detailed structure decisions and review evidence.

Hard convention failures for new or changed runtime code:

- Do not put a feature, screen, endpoint, job, script, style surface, and helper
  set into one file because it is faster.
- Do not add a second responsibility to an already large function, component,
  class, hook, service, or source file. Split the new responsibility first or
  keep it in a named local unit with a clear owner.
- Do not create `utils`, `helpers`, `common`, `misc`, or `shared` buckets for
  unrelated behavior. A new file must be named by responsibility and owner.
- Do not write reusable-looking functions, classes, hooks, components, or
  packages when there is no stable reuse contract. Keep one-off logic local, or
  split it into file-private named units only when that improves review,
  testing, or ownership.
- Do not hide product policy behind boolean flags, nullable option bags, or
  caller-specific modes just to reuse one function or component.
- Do not split code into extra files only to satisfy a line count. Split by
  owner, side effect, state model, contract, platform boundary, or test seam.

## Formatting

- Run the repo formatter or lint fix when configured.
- Do not reformat unrelated files or whole files unless the change requires it.
- Keep generated formatting churn separate from behavior changes when possible.
- Do not hand-edit generated code unless the repo documents that generated file as source.

## Size Signals

Use `../../code-structure-ownership/references/current-guidance.md` for unit
size, ownership, and split criteria. Use
`../../change-size-policy/references/current-guidance.md` for diff-size
decisions.

## Check

- Can a reviewer name the responsibility of this unit in one sentence?
- Does the change match the size of the task? A simple request should be a small
  diff to existing files, not new files, interfaces, layers, or indirection. Each
  new file or abstraction must protect a concrete present risk. See
  `Match Structure To The Problem` in
  `../../llm-coding-discipline/references/current-guidance.md`.
- Does every line carry information a reader needs, or is it ceremony a language
  or framework idiom would remove? See `Avoid Boilerplate` in
  `../../llm-coding-discipline/references/current-guidance.md`.
- Can the behavior be tested without booting unrelated systems?
- Is shared code genuinely reusable, or did it only move duplication behind a
  flag-heavy API?
- Did this follow nearby naming, formatting, and architecture?
- Is any complexity protecting a real product, platform, security, or data risk?
