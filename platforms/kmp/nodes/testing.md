---
keyflow_id: sys_kmp_node_testing
status: review
type: ai-generated
use_when: Adding or changing tests for Kotlin Multiplatform state holders, repositories, processes, Room, or Compose desktop UI, or choosing which test task proves a KMP change.
skip_when: The project has no Kotlin Multiplatform or Compose desktop code.
requires:
  - platforms/compose/nodes/coroutine-flow-ownership.md
---

# KMP Testing

Pick the smallest test that can fail for the changed boundary, and run it on
the target where the behavior lives.

## Rules

| Boundary | Test | Runs as |
| --- | --- | --- |
| state holder | `runTest`, holder scope = `backgroundScope`, injected test dispatcher, assert `state` and `effects` (Turbine or `toList`) | `commonTest` / `desktopTest` |
| repository, mapper, parser | plain unit test with fakes and captured fixtures | `commonTest` or the data module's target test |
| Room | in-memory database with the bundled driver; migration test per version | target test where Room compiles |
| process / PTY adapter | integration test starting a real short command, plus a fake adapter for callers | `desktopTest` |
| Compose desktop UI | `runComposeUiTest { setContent { FooContent(...) } }` with semantics assertions | `desktopTest` |
| visual | screenshot comparison or a captured window of the packaged app | desktop |
| architecture | Konsist or module-graph test (see the architecture enforcement node) | dedicated test module |

- Fakes live next to the contract they fake (a `testFixtures`-style or
  `:core:testing` module) and are shared, not redefined per test.
- Inject clocks, dispatchers, environment and file roots; tests never read
  the real home directory, `PATH` or network.
- Run the exact Gradle task for the affected targets (for example
  `:module:desktopTest`, `:module:allTests`) and report it with its result.
- A test that needs a real tool (git, a shell) checks for it and is skipped
  with a reason only in environments that do not provide it; CI must run it.

## Do Not

- Do not use `Thread.sleep` or real delays; advance virtual time.
- Do not assert on log text or private fields; assert state, effects, files
  or process results.
- Do not mark a Compose test passing from a preview render alone.

## Verification

- The reported task names and counts match what ran, and at least one test
  fails when the changed behavior is reverted.
