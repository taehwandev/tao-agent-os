---
keyflow_id: sys_use_tao_prompt_template
status: review
type: human-reviewed-needed
---

# Use Tao Agent OS Prompt

Paste this into Claude, Gemini/Antigravity/AGY, Codex, or another AI coding
agent when the target repo is not yet wired to Tao Agent OS or when you want a
one-shot task to follow Tao Agent OS explicitly.

Replace the placeholders before sending.

```text
Use Tao Agent OS for this task.

Target repo:
<TARGET_REPO_OR_CURRENT_DIRECTORY>

Task:
<TASK>

Tao Agent OS root:
<TAO_ROOT>

Tao Agent OS stable launcher:
<TAO_LAUNCHER>

VibeGuard human docs:
https://vibeguard.thdev.app/

Rules:
0. Resolve `<TAO_LAUNCHER>` to the installed stable launcher's absolute
   path. Never invoke an internal runtime Python entrypoint directly.
1. Identify the target repo and read repo-local instructions first, including
   AGENTS.md, CLAUDE.md, CODEX.md, .agents/README.md, CONTRIBUTING.md, task
   docs, PRD/ARD docs, equivalent project docs, or explicitly documented local
   override files.
   If the target repo is not explicit or the runtime current directory is
   outside the target, run:
   <TAO_LAUNCHER> agent-entry --request "<USER_REQUEST>" --cwd "<CURRENT_DIRECTORY>" --runtime <RUNTIME>
   Continue only when it returns `selected`; ask me to choose when it returns
   `ambiguous` or `not_found`.
   Do not rely on implicit runtime discovery. If you are Codex-style, explicitly
   read the current project's AGENTS.md; if you are Claude, explicitly read
   CLAUDE.md when present; if you are Gemini/Antigravity/AGY, explicitly read
   the current project's AGENTS.md; if you are another runtime, explicitly read
   the project instruction document that runtime is configured to load.
   If you are Antigravity and cannot confirm the project-root AGENTS.md, stop
   before routing, editing, testing, committing, or reporting completion and ask
   for bridge repair.
   Do not mention setup, hook, permission, helper, label, or background metering
   details in normal conversation unless I explicitly ask about that subsystem.
   If a response exposed those background details, do not finish with an
   apology-only message. Repair the action path or stop with the specific
   blocker.
2. Do not assume this runtime automatically loaded Tao Agent OS. Explicitly
   read <TAO_ROOT>/AGENTS.md. Let the start hook route the smallest
   required document set; open <TAO_ROOT>/index.md only for a simple
   answer-only lookup or an explicitly accepted routing fallback.
3. Do not copy the whole Tao Agent OS library into this repo. Link only the
   relevant root, index, workflow script, and selected cards. If you edit
   committed repo-local instruction files, use a portable root reference such
   as ${TAO_HOME} or a repo-relative pinned path like
   .agents/tao-agent-os; do not commit a personal absolute path. Full local
   paths are acceptable only in this one-shot prompt, shell env setup, or
   uncommitted user-level runtime bridges.
4. VibeGuard is required. Before editing documentation, code, config,
   dependency, data, deployment, or credential surfaces, inspect existing
   VibeGuard files and agent instructions. If they already exist, ask the
   application drill before running setup or update. Then apply the selected
   VibeGuard mode with the published package command and <TAO_ROOT>
   as the rule source. The VibeGuard site is a human reference and does not
   need to be fetched by the agent. If the VibeGuard command cannot run, stop
   and report the blocker. Use VibeGuard update only when I explicitly choose
   to refresh an existing managed block.
5. For multi-step tasks, run this once before selecting task documents,
   editing, reviewing, committing, or reporting completion:
   <TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <COMMAND> --request "<USER_REQUEST>" [--platform <PLATFORM>] [--concern <CONCERN>]
   It performs workflow routing/preflight and returns the command manifest. Do
   not separately repeat workflow list, classify, route, or preflight.
   Do not wait for me to name document keywords. Let routing/search infer the
   work surface from the request, platform, concern, and touched files; use
   workflow-doc-surfaces.json and the local document graph as inputs; read the
   route `required_docs` before editing or reviewing; and treat graph neighbors
   as `reference_docs` unless the route promotes them to `required_docs`.
   If routing/search misses a clearly relevant platform, concern, or document
   surface, stop and report the gap instead of proceeding from memory.
   After the start hook and required-doc reading, consume
   `parallel_execution.delegation_policy`. If this runtime exposes workers and
   at least two meaningful slices have disjoint scopes, a stable contract, an
   integration owner, and focused verification, delegate automatically without
   waiting for me to request multi-agent work. Otherwise record the concrete
   serial reason. Use Codex native workers, Claude Agent/Task workers, or the
   Gemini/AGY Antigravity agent runner according to the active runtime. At each
   parent-to-worker boundary, run:
   <TAO_LAUNCHER> handoff --project <TARGET_REPO> --rules <TAO_ROOT>
   This refreshes the provider-neutral, content-free execution capsule and
   validates it once. A ready and valid handoff lets the worker reuse the
   parent's route, preflight, and required-doc manifest and skip duplicate
   startup. An invalid handoff is a successful fallback decision that requires
   the worker's normal lifecycle; never reuse mismatched capsule state. The
   parent is the sole gate-ledger owner. Workers use worker-specific evidence
   paths, return scoped evidence, and never overwrite the parent ledger,
   including after an invalid handoff fallback. For a Codex leaf, use `dispatch
   --execute` only when the selected model, reasoning effort, sandbox, or
   required isolation differs from the parent. When the selected profile and
   sandbox match and isolation is unnecessary, stay in the current process or
   use a native worker instead of launching a fresh Codex process.
   If the request is a direct question, answer it before routing or editing.
   If the direct question asks how to start app, product, or feature work,
   answer with PRD -> ARD -> implementation gates before lower-level coding
   steps. If the task then proceeds into code, use the product route unless an
   existing PRD/ARD or repo-local instruction makes the slice clearly trivial.
   If the workflow router cannot run, stop and report the blocker before
   continuing.
   Use the lowest capable effort level. Do not use deep reasoning or a
   specialist agent for clear, low-risk requests unless local evidence expands
   the scope.
6. Read every `required_docs` entry from the route before editing or reviewing.
   The start hook records the route, git status, and VibeGuard result in
   <TARGET_REPO>/.tao/preflight.json. Do not add a second document
   confirmation step.
7. Keep a gate execution ledger from the route output. Mark each required gate
   when it is executed or fails, include concrete evidence such as a command,
   file, diff, manual check, or decision note, and assign only one of two public
   signals: `🐱🟢 SUCCESS` for executed with evidence or `🐱🔴 FAIL` for blocked,
   failed, missed, or missing evidence. Do not reconstruct the ledger from
   memory at the end, and do not report any third gate state.
8. After each completed or failed gate or task step, show:
   Gate signal: 🐱🟢 SUCCESS | gate: <gate> | evidence: <evidence> | next: <next gate>
9. If any required gate was not executed, stop before final report, commit,
   release, or handoff. Roll back only dependent agent-made changes after the
   failed checkpoint when safe, preserve user-owned changes, and run the
   retrospective workflow. Improve and verify the canonical Tao Agent OS doc,
   hook, validator, or test before resuming that checkpoint. Allow one repair
   cycle only; stop if the same failure remains or the repair is unsafe or
   ambiguous.
10. When a gate is missed, the retrospective must include `AI mistake`,
   `Proposed fix`, and `Discussion result`. Write the discussion result in the
   user's language for the task.
11. Load only the listed documents and the smallest relevant platform, product,
   or common cards. Do not load every shared document by default.
12. Discover the repo stack before choosing package managers, framework APIs, or
   project commands. Preserve user-owned worktree changes.
13. When commands fail, read stdout/stderr and fix only the smallest relevant
   issue. Do not blindly retry, delete tests, or silence errors.
14. Ask only blocker questions. Prefer concrete options with tradeoffs and a
   recommended default.
15. Before finishing, confirm every required route gate is `🐱🟢 SUCCESS` with ledger
    evidence. Before executing wrapper commands, replace
    `<TAO_ROOT>` with the resolved absolute path; do not leave
    `$HOME`, `${HOME}`, `~`, or a relative path in the executable command. When
    available, run:
    <TAO_LAUNCHER> finish --project <TARGET_REPO> --rules <TAO_ROOT>
    Record manual gate facts first with `<TAO_LAUNCHER> gate` or `gate-batch`.
    Finish is read-only: it accepts no inline gate evidence and never mutates
    the ledger while validating completion.
    Missing wrapper evidence or missing route gate evidence is non-compliant.
    If `--request-classified` is used, include `--classification-evidence`. The
    flag is honored only for a delegated worker backed by a ready and valid
    parent execution capsule; otherwise pass `--request "<USER_REQUEST>"` and
    let the classifier run.
    Work routes require resolved-scope evidence such as `clear-scoped`,
    `answered ... separate actionable`, or `blockers resolved`; weak markers
    such as `classified`, `done`, `clarified`, or `no blockers` are not
    sufficient.
    If the request asks for Grill-Me or classification returns `grill_me: true`,
    missing Grill-Me protocol or `/grilling` session evidence is `🐱🔴 FAIL`.
    If final VibeGuard is `Needs review`, report that state and pass
    `--allow-vibeguard-review "<reason>"` only when the review state is
    acceptable. Then report changed files, checks run, skipped checks, and
    residual risk.
```

## Choosing The Route

Use these common command profiles:

- General task: `task`
- Product PRD/ARD to implementation: `product`
- Feature: `feature` only after PRD/ARD is satisfied or unnecessary for a
  scoped trivial slice
- Bug or failing command: `bugfix --concern failure`
- PRD/product requirements note only: `prd`
- Documentation update: `docs --concern wiki`
- Documentation review: `docs-review --concern wiki`
- Code review or commit readiness: `review`
- Release or versioning: `release`

Add `--platform web`, `--platform ios`, `--platform android`,
`--platform server`, or `--platform application` when a platform is touched.
Repeat `--concern` for each touched risk area.
