---
keyflow_id: sys_agent_operating_skill
status: stable
type: human-reviewed-needed
---

# Agent Operating Skill

Use this reference for an unresolved operating procedure. The reading contract
in `../SKILL.md` and lifecycle in `AGENTS.md` remain the entrypoints; this
reference does not create additional gates or a second startup checklist.

## Execution Decisions

Before implementation:
- Identify the target and existing user changes; read repo-local instructions
  and inspect stack manifests, lockfiles and configuration before choosing
  commands, dependencies or framework APIs.
- Resolve request clarity and effort using
  `common/skills/task-intake-effort-routing/SKILL.md`. Answer direct questions
  before routing; questions about starting product delivery need the PRD →
  ARD → implementation sequence. Ask only about unresolved choices that affect
  behavior, scope, risk, acceptance or verification.
- For behavior-changing work, search for and read the repo's PRD, spec, ARD,
  issue, design note or other source of truth. If none exists, record the
  search and decide whether the user request suffices or a spec is needed.
- Give a compact user-visible alignment brief before requirements or edits:
  shared understanding, possible differences, unsupported assumptions, and
  any blocker question or safe default. If skipping a PRD, state why; an
  internal note written afterward is not alignment. For prose, a tone cue
  does not establish genre, point of view or structure: clarify genuinely
  ambiguous writing modes.
- Use one successful `<TAO_LAUNCHER> start` for tracked work and consume its
  required_docs manifest. Do not repeat list/classify/route/preflight or add a document
  receipt. Read-only lookup stays stateless under `AGENTS.md`; legacy runs
  retain their pinned gates. Commit-only requests use `commit`/`git_commit`;
  an already authorized, reviewed unit follows the same-session commit
  continuation contract without another lifecycle.
- Apply preflight's accepted/promoted global lessons unless repo-local
  instructions conflict. Preserve the route's required evidence fields:
  run state names current state, next/resume transition, evidence, stop and
  blocker; a cycle contract names type, inputs, allowed/forbidden changes,
  verification and next/stop condition. Keep review separate from
  implementation unless review-response work is requested.
- Before a cross-file or package boundary change, name the boundary, folder
  map, file split, allowed/forbidden imports, callers and nearest test. Do
  not start by accumulating unrelated roles in a generic shared/utils/manager
  owner. Resolve the primary acceptance repo and checkpoint the secondary
  source of truth, mode, scope, session model and cross-repo verification
  before a secondary-repo write.
- Use `parallel_execution.phases` for independent reads and orientation;
  serialize dependencies. Start may overlap independent reads after intake,
  but edits and other writes wait for its success. For delegation, follow
  `AGENTS.md` and the selected collaboration procedure: record owned and
  forbidden files, stable contracts, acceptance and integration owner in
  `.tao/agent-delegation-plan.json` before workers start. Serialize shared
  contracts, generated files, migrations, dependencies, release configuration
  and architecture boundaries.

During implementation:
- Make the smallest effective change using existing architecture and naming;
  preserve user changes and keep unrelated refactors out.
- Identify applicable data, auth, permissions, billing, persistence, filesystem,
  network, external-state and release risks. Protect secrets, client keys,
  private prompts, local configuration, logs, analytics and crash reports.
- Update affected source-of-truth documentation when behavior, workflow,
  public contracts, durable acceptance or operator actions change. Otherwise
  identify the checked source and explain unchanged/not-applicable status.
- Add, update and run the nearest useful test for behavior or workflow changes;
  start with the narrowest reliable verification. Mocked, placeholder and TODO
  behavior cannot be reported as complete.

Before completion:
- Follow only the active route's required gates and evidence schemas.
  Documentation evidence names the decision, source path/class and reason;
  required code evidence includes ambiguity, docs freshness, tests and split
  decision when the route calls for them.
- A required check cannot pass with skipped, unavailable, deferred or
  not-applicable evidence unless its contract permits that outcome. Report
  unresolved blocking/must-fix/should-fix issues as failure. Show concise
  evidence-based gate results rather than reconstructing pass-through prose.
- Run a required review hook once, then batch only missing manual gates.
  Hook-owned gates never belong in manual payloads. Observe batch success
  before calling finish in a separate invocation; a rejected batch records
  nothing. Reuse its unchanged Remaining route gates snapshot.
- Run the finish hook before final report, handoff, commit or release.
  Direct preflight/finish scripts are lower-level diagnostics or unavailable-hook fallbacks,
  not additional steps. If a check cannot run, state the reason and remaining
  risk; report changed behavior, observed verification and useful file links.

Detailed gate schemas and cycle fields are owned by
`workflows/skills/scripted-agent-workflow/references/current-guidance.md` and
`workflows/skills/cycle-contract/references/current-guidance.md`. Consult
them only when the active requirement is unresolved.

## Reading And Investigation Mechanics

These expand the Need-Driven Reading Contract in `../SKILL.md`; they are the
detail behind its steps, not a second contract.

- For a new isolated task, when the installed setup contract permits worktree
  creation before start, prepare the worktree and start the implementation there.
  Do not open a source-checkout implementation run merely to repeat it in the
  worktree. If setup requires a source run, follow its supported transfer or
  settlement procedure; do not bypass that requirement or leave duplicate active
  runs. Local integration remains a separate scope with its own authority.
- For adapter work, establish whether the existing contract is a one-way
  projection or a reversible conversion. Characterize preserved and omitted
  fields and identity mapping before changing consumers. A round-trip criterion
  is not permission to invent a reverse conversion or change persistence.
  Consult history only to resolve an identified contract ambiguity; once current
  contracts, consumers and tests resolve it, stop expanding that investigation.
- Size a read to the tool's output limit, including the outer result limit
  when batching calls. Keep large documents in separate results or consecutive
  bounded ranges through EOF. A truncated result is incomplete: recover only
  its missing ranges, not the same whole batch.

## Applying Hook Guidance At The Decision Point

The contract is in `../SKILL.md`: hooks own mechanical admission and
validation, the agent owns scope, evidence truth and the next authorized
action. This is how that applies to a rejection and to reuse.

Treat a rejection according to its reported boundary. An invalid argument or
missing evidence field calls for correcting that input, not restarting the
task or repairing product code. A real failed check needs diagnosis at its
owner. A session/evidence mismatch needs reconciliation with the intended run;
do not infer that finish revoked permission or create a replacement run merely
because a command was blocked. Preserve actual approval and isolation limits.
Successful hooks validate their stated checks, not behavioral equivalence or
the correctness of an agent's explanation of a failure.

Later discovery is a normal correction point. Complete a missed check or repair
an in-scope defect when it becomes known; do not restart valid earlier work just
because it was found during review or verification. Record what was actually
checked then, without claiming it happened before implementation. Recheck the
affected result and refresh any evidence invalidated by the change; retain
unaffected evidence only while its state, authority and freshness still match.
A prerequisite that truly had to precede an action, such as authorization,
cannot be supplied retroactively. Use the missed-gate recovery in
`common/skills/worktree-hygiene/references/current-guidance.md` for that case.

For sustained goals, each new implementation unit retains its required tests,
review and integration checks. Reuse applies only to evidence whose covered
state and required freshness still match; it is not a reason to skip the next
unit's verification. Judge process quality by whether each decision had the
needed guidance and evidence, not by minimizing reads, tests or lifecycle calls.
This contract adds no gate, receipt, approval round or mandatory preview.

## Stale Evidence And Recovery

If tracked read-only finish reports that the project or rules root changed after
start, treat it as real stale-input evidence, including a clean concurrent HEAD
advance or non-Git guidance change. Do not revert the concurrent change or
weaken the fingerprint check. Follow
`workflows/skills/retrospective-learning/references/failure-repair.md`:
wait for the writer to settle, read changed required guidance, revalidate the
original scope, generate a fresh start/preflight snapshot and resume the failed
checkpoint. Keep the original evidence path for the repair receipt when changed
guidance is outside the product checkout. An explicitly read-only non-intrinsic
route may resume without that declaration only under its authorized broader
scope; intrinsic read routes remain read-only. This recovery does not turn
stateless lookup into a tracked run.

A genuine missed prerequisite or failed gate requires the retrospective
correction plan before retry/completion. Apply safe scoped repairs and cite the
plan on retry; recurring lessons belong in their canonical docs, tests,
validators or hooks. Malformed evidence submissions instead follow the input
correction rule above.

## Task-Specific Guidance

The route selects procedures; this is not an additional reading queue. Use
`workflow query` for an unresolved topic. If routing is unavailable, report
the blocker before the approved `index.md` fallback. Product delivery uses
`workflows/skills/product-architecture-delivery/SKILL.md` before lower-level
feature work unless the request is already trivial and scoped.

Preserve these conditional dependencies when the task actually changes them:
- File/module ownership, public contracts, dependency direction, reusable
  fixtures, fakes or assertion APIs require the structure/SOLID/reusable-design
  bundle: `common/skills/code-structure-ownership/SKILL.md`,
  `common/skills/solid-design-principles/SKILL.md` and
  `common/skills/reusable-code-design/SKILL.md`. A new shared boundary needs
  its owner/import/caller/verification note and, for multiple roles, a file
  split before edits.
- Publishable long-form prose uses `common/skills/writing-workspace/SKILL.md`
  with `common/skills/human-authored-writing/SKILL.md`.
- Android typed navigation, deep links, mixed Activity/Compose routing or
  route callbacks require `platforms/android/skills/android-architecture/SKILL.md`
  and `platforms/android/skills/android-module-structure/SKILL.md`, plus the
  structure bundle for boundary/API/test-support moves. Exported components,
  app links, WebView, permissions and credentials also require
  `platforms/android/skills/android-security/SKILL.md`.
- Android Compose performance work requires
  `platforms/android/skills/android-compose-ui/SKILL.md`,
  `platforms/android/skills/android-review/SKILL.md`,
  `platforms/android/skills/android-external-skill-source-coverage/SKILL.md`,
  and testing/verification cards. A performance claim needs relevant
  measurement or an explicit statement that only structural risk was reduced.
- Android SDK/platform-surface changes require the matching architecture,
  module, Compose or security card and the no-omission source manifest in
  `platforms/android/skills/android-external-skill-source-coverage/SKILL.md`
  before edits.

## Output Contract

Report what changed, what was actually verified and remaining risk. A short
paragraph is enough for small tasks; unavailable verification is explicit.
