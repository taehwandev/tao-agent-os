---
keyflow_id: sys_workflows_review_and_commit_md_skill
status: stable
type: ai-generated
---

# Review And Commit Workflow

Use for final review and commit preparation.

## Read

For a `commit` or `git_commit` follow-up, including push and PR, use this
entrypoint's publication minimum. Detailed cards are on demand; reuse complete,
unchanged readings.

- `references/current-guidance.md` for `--commit-ready` preparation, unresolved
  review procedure, or an explicit route requirement.
- A related skill only for a concrete finding, an unresolved in-scope question,
  or an explicit applicable project requirement. Follow its detailed reference
  only if the entrypoint does not answer that question.

## Process

1. Read this entrypoint; open detail only for a concrete unresolved decision.
   Commit/PR work alone does not require development or branch-strategy cards.
2. Reuse reads and tests when `HEAD`, bytes, target, and external state are
   unchanged. Review the final diff once. The Review Hook's VibeGuard audit
   replaces an adjacent identical audit; reuse the gate-batch remaining list.
3. Repair a final-review finding only with a reproducer, impact, evidence this
   diff caused it, owner, and nearest falsifying check. Give a proven blocker
   one bounded repair and affected recheck; otherwise keep it as follow-up or
   stop publication.
4. Run Review Hook with its advertised outcome and every required evidence
   field, never bare `review`. For any changed multi-role package, even an
   existing one, pass the exact labeled contract separately through
   `--structure-review-evidence`, not `--boundary-plan-evidence`:
   `owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...; verification: ...`.

## Commit And PR Minimum

Stage only the exact unit; review its staged diff and reuse evidence only while
the covered bytes and target are unchanged. Stop on findings or drift; no hidden
implementation under `commit`. Before push, check remote, visibility, strict
safety gate, and authority for the exact action. Reuse an open PR with the same
head/base, give it a substantive body, and merge only after mergeability and
required checks are known. Fast-forward a clean local `main` afterward.

When an implementation request also authorizes commits, prepare the exact
staged unit before final review and finish. An eligible local commit then
continues directly without a second lifecycle, under the same-run continuation
contract in `common/skills/commit-workflow/references/current-guidance.md`.
New commit authority, changed scope, or stale evidence uses the lightweight
`commit` route. A rejected command is not proof that
unrelated staging must be changed. Check the declared action, completed-run
binding and supported command form first; preserve unrelated staging and
request new authority only for a genuinely necessary change to it.

Load `common/skills/commit-workflow/references/current-guidance.md` only for an
unresolved branch, tracker/signing, mixed/generated commit,
security/migration/release risk, or publication exception.

## Do Not

- Use this canonical bundle, not legacy flat paths or unrelated references.
- Do not select `release` or `ship` for an ordinary branch push or pull request.
  Those publication follow-ups stay on the lightweight `commit` route unless
  the request also names a release artifact, deployment, tag, or rollout.
- Do not rediscover an advertised command with `--help`, reopen unchanged source
  after reviewing its final diff, or turn a non-blocking review observation
  into implementation work.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
