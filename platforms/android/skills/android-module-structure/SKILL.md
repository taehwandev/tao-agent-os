---
keyflow_id: sys_platforms_android_android_module_structure_md_skill
status: review
type: ai-generated
---

# Android Module Structure

This card owns where Android code lives: package vs module, the
`api`/`impl`/`ui` split, dependency edge direction, moving existing code
between modules, build-logic convention plugins, and Hilt module placement.

## Steps

1. **Detect the repo's convention.** Read `settings.gradle(.kts)`, the
   existing module families and their names, `build-logic` plugin ids, and one
   neighbouring feature. Repo-local names, module families, and DI style win;
   the shapes below are the fallback when the repo has no convention.
2. **Look for an existing owner.** Search the target modules for a contract
   that already covers the behavior. If one exists, converge callers onto it
   instead of creating new files.
3. **Choose the smallest boundary.** Walk the ladder and stop at the first rung
   a named caller needs:
   `private file -> feature package -> feature module -> api + impl
   -> api + impl + ui -> core capability`. MUST read
   [module-boundaries.md](references/module-boundaries.md) before creating any
   `api`/`impl`/`ui`/`assertions` module or package boundary note.

   | Proven need | Smallest shape |
   | --- | --- |
   | Feature stays local to one module | one unsplit module |
   | Another module navigates to, launches, or compiles against it | `api` + `impl` |
   | A named consumer outside `impl` renders the same concrete surface | `api` + `impl` + `ui` |

4. **Place ownership.** `api` holds the whole navigation contract (destination
   type, arguments, deep link, result, public events, `navigateTo<Feature>`);
   `impl` holds holder, ViewModel, state, content, entry binding, and any
   Activity. MUST read [module-layout.md](references/module-layout.md) before
   choosing a module family or core capability, and
   [feature-package-structure.md](references/feature-package-structure.md)
   before adding feature subpackages.
5. **Check dependency edges.** Forbidden: `api -> impl`, `api -> ui`,
   `ui -> impl`, navigating caller `-> impl`/`-> ui`, `repository-api ->
   repository impl`, `repository -> feature`, `core -> feature`,
   `designsystem -> feature`, `domain -> UI/Android/DTO`. MUST run the
   Dependency Edge Verification in
   [module-layout.md](references/module-layout.md) for every edge you add.
6. **Entry contracts.** MUST read
   [compose-entry-contracts.md](references/compose-entry-contracts.md) before an
   `api` module exposes a `@Composable`, Activity, provider, or registry entry.
7. **DI and build logic.** MUST read
   [di-build-logic.md](references/di-build-logic.md) before editing
   `build-logic`, convention plugins, Gradle dependency blocks, or Hilt modules.
8. **Moving existing code.** MUST read
   [split-and-migration.md](references/split-and-migration.md) before moving
   any file, package, or module; it owns the pre-edit gate, copy-first parity,
   end state, and split hazards.
9. **Split files.** Apply the file rules in
   [current-guidance.md](references/current-guidance.md#file-and-class-split).
10. **Review.** Run [review-checklist.md](references/review-checklist.md)
    before reporting.

## Source Map

| Need | Reference |
| --- | --- |
| Split decision, ownership, naming, example packet | [module-boundaries.md](references/module-boundaries.md) |
| Module families, core capabilities, edges | [module-layout.md](references/module-layout.md) |
| Feature package gate | [feature-package-structure.md](references/feature-package-structure.md) |
| Compose/Activity entry, registries, Navigation 3 | [compose-entry-contracts.md](references/compose-entry-contracts.md) |
| Convention plugins, Hilt placement, cleanup | [di-build-logic.md](references/di-build-logic.md) |
| Moving code, bridges, split hazards | [split-and-migration.md](references/split-and-migration.md) |
| External Android skill surfaces | [skill-source-coverage.md](references/skill-source-coverage.md) |
| Architecture tracks and runtime boundaries | [android-architecture](../android-architecture/SKILL.md) |

## Do Not

- Create modules to fill a template shape; each module needs a named caller.
- Extract `ui` for a preview, an internal package, or the feature's own
  Activity.
- Hide a single concrete composable behind an interface with one
  implementation and one `@Binds`; call the composable directly.
- Fix a wrong edge by moving it behind a DI interface.
- Copy a reference app's module list, plugin ids, or package names.

## Stop If

- You cannot name the caller or consumer that needs the boundary.
- The package boundary note cannot name a forbidden import.
- A move adds glue to the host module and you cannot say what still has to
  move and when the glue is removed.
- A UI-bearing move would change what renders before parity evidence exists.

## Verification

- Compile each changed module and at least one real consumer; compile a
  navigating caller against `api` alone when `api` changed.
- Run the forbidden-import and Gradle-edge searches from
  [module-layout.md](references/module-layout.md).
- For build-logic changes, follow the verification order in
  [di-build-logic.md](references/di-build-logic.md).

## Report

- Chosen shape: one unsplit module | `api` + `impl` | `api` + `impl` + `ui` |
  core capability | package only.
- The caller or consumer that justifies it, and why the next-smaller boundary
  fails.
- Dependency edges added and removed, and the integration owner.
- For moves: host files deleted vs added, remaining bridges, and whether the
  migration is complete or partial.

When changing routing or this card, confirm the route loads this entrypoint and
that every link resolves.
