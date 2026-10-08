---
keyflow_id: sys_kmp_node_desktop_process_pty
status: review
type: ai-generated
use_when: Starting, supervising, reading from or stopping child processes, PTY sessions, CLI tools, browser or device bridges, or file watchers from a Kotlin JVM desktop app.
skip_when: The change only renders process state already exposed as a Flow by a capability module, or the target has no JVM runtime.
refines:
  - platforms/application/skills/application-system-integration/references/current-guidance.md
requires:
  - platforms/compose/nodes/coroutine-flow-ownership.md
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP Desktop Processes And PTY

The parent card owns adapter boundaries and cleanup duties. This node adds
the JVM mechanics for processes a desktop app starts.

## Rules

- One capability or data module owns each process kind. It exposes a contract
  (start, write, resize, stop, a `Flow` of output and exit) and hides
  `Process`, `PtyProcess`, streams and sockets. Feature code never sees them.
- Build commands as an argument list (`ProcessBuilder(listOf(...))`,
  `PtyProcessBuilder(arrayOf(...))`). Never pass a shell string assembled from
  user input; when a shell is required, pass user values as separate
  arguments or environment entries.
- macOS GUI launches do not inherit the login shell `PATH`. Resolve the user's
  environment once (login shell `-l -c env` with a timeout, or explicit tool
  paths from settings), cache it, and pass it to every child; report a missing
  tool as a typed failure instead of "command not found" text.
- Blocking reads run on `Dispatchers.IO` in a coroutine owned by the session.
  Cancelling that coroutine does not unblock `read()`: close the stream or
  destroy the process in `finally` / `invokeOnCompletion`, then await exit.
- Stop is staged: polite signal or exit command, bounded wait, then
  `destroyForcibly()`. For PTY sessions terminate the process group so shells
  do not leave grandchildren behind. Record the exit code and reason.
- Apply backpressure to output: buffer with a bounded `Channel` or a ring
  buffer and coalesce redraws; never append unbounded output to UI state.
- PTY resize follows the visible terminal size and is debounced; send it to
  the PTY, not by restarting the process.
- Supervise long-lived helpers (headless browser, emulator bridge, language
  server): pick free ports at start, health-check, restart with backoff, and
  kill orphans from a previous crashed run on startup when they are provably
  ours (pid file or tagged command line).
- Register one app-level shutdown path that stops sessions in order. A JVM
  shutdown hook is a last resort for force-quit; it must be idempotent and
  fast.
- Parse tool output (git porcelain v2, device lists, status JSON) in the
  owning data module with fixture tests; request machine-readable formats
  (`--porcelain=v2 -z`, `--json`) instead of parsing human output.
- `WatchService` on macOS falls back to slow polling. For responsive project
  trees use a native-backed watcher or explicit refresh triggers, and guard
  app-originated writes per the parent card.

## Do Not

- Do not start a process from a composable, a state holder constructor, or an
  `init` block.
- Do not keep a process alive after its owning session, window or app scope is
  cancelled.
- Do not log full command lines, environments or terminal output that may
  contain secrets; redact tokens and home paths.
- Do not treat exit code 0 as success for tools that report failure on
  stderr only; parse the documented result.

## Verification

- Integration test that starts a real short-lived process or PTY (for example
  `echo`), reads output, resizes, stops it, and asserts the process and its
  children are gone.
- Parser tests over captured fixture output, including empty, error and
  non-ASCII paths.
- Launch the packaged app from Finder (not a terminal) and confirm tools on
  the user's login `PATH` are found.
