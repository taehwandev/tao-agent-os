---
keyflow_id: sys_toolbar_publication_retrospective
status: review
type: ai-generated
---

# Toolbar Publication Retrospective

The compact Project toolbar was committed to TaoIDE main as `b042f544`.
The user reported roughly 90 minutes of delay and then explicitly stopped
further verification. This document records observed causes, not a measured
allocation of that entire duration.

## Agent Execution Errors

- Verification expanded beyond the changed UI after focused checks passed.
  Unrelated dirty-checkout failures and screenshot differences consumed time
  without establishing whether the intended commit was correct.
- The shared checkout kept changing. Repeated builds against that checkout
  and recreated source archives changed the verification subject repeatedly.
- A successful review was followed by concurrent changes before finish. The
  resulting stale attestation was a valid refusal, not permission to weaken
  the freshness check.
- Some orchestration calls continued to dependent work after an earlier
  command failed. Existing operating guidance already requires checking each
  result before a dependent action; the agent failed to apply that rule.
- Custom publication wrappers were introduced despite an existing literal Git
  command contract. After finish, their unknown effects correctly prevented
  publication through that wrapper. Literal Git commit completed the request.

These are execution mistakes. Adding another mandatory review, test suite,
receipt or learning cycle would repeat the problem rather than resolve it.

## Command Interpretation Defects

1. Effect classification unwraps safe environment prefixes, but declared path
   roles previously inspected the wrapped tokens. A known hook's read-only
   `--rules` operand could therefore become a protected write target when the
   same hook was wrapped by an inert environment assignment.
2. `git diff --output=<artifact>` was conservatively treated as a write by the
   Git parser, but the effect layer could not describe that write. Repository
   inputs also remained possible write targets. A supported local artifact
   operation was consequently reported as an unknown command.
3. An index-only patch application was treated like a working-tree source
   edit. This obstructed preserving unrelated staged hunks after a commit
   prepared with a separate index. The index boundary needs a specific
   contract; unrestricted `git apply` must remain a source-writing operation.

Unrecognised executor environment variables, including Git variables that
change the verification subject, are not made inert by these fixes. They must
not silently inherit a read-only or lifecycle allowance.

## Corrections

- Interpret path roles through the same existing safe environment unwrapping
  used for command classification, retaining positions in the original argv.
- Describe a Git diff artifact as a local write only when removing one exact
  output option leaves an otherwise read-only Git diff. Only its output token
  remains a possible write target; external differs and configuration overrides
  retain the conservative contract.
- Use literal Git publication commands, and keep normal-index reconciliation
  distinct from source changes and additional commits.
- Stop verification when the user requests it. Report the resulting lack of
  validation explicitly instead of running another check or claiming a pass.

No additional builds or tests were run after the user's stop instruction.
The user subsequently authorized local main integration of the prepared
repair. The parser changes remain unverified; integration does not claim
passing tests or verified runtime behavior.
