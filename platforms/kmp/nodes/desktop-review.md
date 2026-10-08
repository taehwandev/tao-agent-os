---
keyflow_id: sys_kmp_node_desktop_review
status: review
type: ai-generated
use_when: Reviewing or accepting a Compose Multiplatform desktop change that touches windows, processes, Swing interop, state holders, DI, Room, packaging or module boundaries.
skip_when: The change has no desktop JVM target, or another review card already covers every touched surface.
refines:
  - platforms/application/skills/application-review/references/current-guidance.md
---

# KMP Desktop Review

The parent card owns findings priority and output shape. Add these desktop
checks for the surfaces the diff touches.

## Rules

Block approval when the diff shows any of:

- A feature or stateless composable importing `java.io.File`, `ProcessBuilder`,
  a PTY type, a DAO, a DI graph type, or AWT/Swing types outside a declared
  platform leaf.
- A process, watcher, socket or database opened without an owner that stops
  it on cancel, window close and app quit.
- IO, process or database work on the Swing (main) thread, or `runBlocking`
  in UI code.
- A state holder that creates its own scope, holds platform handles, or is
  kept alive and re-bound with new arguments instead of re-created per key.
- A command reachable from menu, shortcut and button through different code.
- A shell string built from user input, or a log line with unredacted
  environment, tokens or terminal output.
- A new allowlist entry in an architecture test, or a new
  `feature -> feature` / `core -> feature` edge.
- Packaging changes without a signed, notarized, launched artifact check, or
  a new native binary without a signing step.
- A Room schema change without a version bump, exported schema and migration
  test.

Also check, and report as findings when missing:

- The exact Gradle test tasks that ran for each affected module.
- A visual capture for renderer, font, scale or Swing-embedding changes.
- Window state restore and quit cleanup when shell code changed.

## Do Not

- Do not approve on compile success alone for process, window, packaging or
  persistence changes.
- Do not accept "works on my machine" for PATH-dependent tools; require a
  Finder-launched check.

## Verification

- Each finding names file, rule, impact and the check that would prove the
  fix; the report lists unchecked surfaces explicitly.
