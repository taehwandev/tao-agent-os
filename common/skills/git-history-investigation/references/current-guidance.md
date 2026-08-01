---
keyflow_id: sys_git_history_investigation
status: review
type: ai-generated
---

# Git History Investigation

Use when the task is to recover why existing code is the way it is: why a line
or block exists, whether apparently strange or dead code is safe to remove, or
which commit really authored a behavior. The output is an evidence-backed
verdict, not a plausible story.

## Use When

- Asked why a line, function, or workaround exists, or who introduced it and
  why.
- Asked whether suspicious-looking code is safe to delete.
- Asked for the origin, rationale, or history of existing code.

## Blame Properly

Never run bare `git blame`. Bare blame routinely names formatting, lint, or
refactor commits instead of the commit that authored the line's meaning.

```
git blame -w [--ignore-revs-file <ignore-revs file>] -L <start>,<end> -- <file>
```

- Always pass `-w`.
- Pass the repo's blame ignore-revs file whenever one exists (commonly
  `.git-blame-ignore-revs`); its presence lists commits the maintainers already
  judged as noise.
- Escalate to `-C -C -C` (follows code moved or copied across files) only when
  the cheap blame dead-ends. On large repositories, and especially on partial
  clones, copy detection can take minutes or hang while fetching old blobs:
  keep the `-L` range tight, set a command timeout, and fall back to
  `git log -S` tracing when it stalls.

## Noise-Commit Classification

For each commit blame names, judge whether it is a noise commit — one that
touched the line without authoring its meaning. Check evidence in cost order:

1. Ignore-revs listing — the SHA appears in the repo's ignore-revs file:
   noise, no further checks needed.
2. Message pattern — the subject states mechanical intent (`format`, `lint`,
   `style`, `whitespace`, `indent`, `rename`, `move file`, repo-wide reformat
   sweeps). A pattern match is a suspicion, not a conviction; confirm with the
   diff check.
3. Diff check — `git diff <sha>^ <sha> -w -- <file>`. An empty `-w` diff
   proves whitespace-only. A non-empty diff can still be noise (quote-style
   swaps, trailing-comma or semicolon churn with zero semantic change); judge
   the diff content, not just the flags.
4. Mass-touch shape — `git show <sha> --stat`: hundreds of files changed under
   a mechanical message is the classic repo-wide reformat.

If the commit is noise, re-run blame excluding it, accumulating flags across
iterations:

```
git blame -w --ignore-rev <noise-sha> [--ignore-rev <another>...] -L <start>,<end> -- <file>
```

Cap the loop at 5 iterations. At the cap, stop and report the peeled layers
honestly with an `unknown` verdict instead of looping on a pathological
history. The loop ends when blame names the commit that actually authored the
line's meaning: the origin commit.

## Moved or Extracted Code

When the loop lands on a commit that created or split the file (extractions,
moves, renames), `-C -C -C` often fails to cross the file boundary because
copy detection has size thresholds. Check `git show <sha>`: if the same commit
deleted the line elsewhere, the line was moved, not authored. Trace the true
origin with `git log -S'<distinctive fragment>' --oneline`, which finds every
commit that added or removed that code anywhere in history; the oldest hit is
the origin candidate. Use `git log -G'<regex>'` when the fragment needs a
pattern rather than an exact string. Resume the classification loop on that
candidate.

## Evidence Chase

For the origin commit:

- Read `git show <sha>`: the change, its message, author, and date.
- Extract references from the message: PR numbers, issue numbers, ticket ids,
  URLs. Each is a lead.
- When the PR host's API or CLI is reachable and authenticated, chase the
  origin commit to its PR and any linked tracker issues. Review comments often
  record the real rationale, rejected alternatives, and promises to remove
  later — reasons that exist nowhere in git objects.
- When the PR host or tracker is unreachable, complete the verdict on git-only
  evidence (message, diff, `git log --follow -- <file>`) and state the gap
  explicitly in the report. Do not stall and do not fail the investigation on
  a missing tool.
- Check whether the original reason still holds today: does the worked-around
  bug still exist, and is the platform or dependency version it served still
  supported? Consult in-repo support matrices, dependency versions, and
  changelogs. This check, not the history alone, decides the verdict.

## Verdict

Close every investigation with exactly one verdict:

- `reason still holds` — the motivation was real and still applies. Keep the
  code.
- `obsolete` — the motivation was real but no longer applies. Removal is safe
  with stated precautions; when the origin records a reproduction scenario,
  keep it as a regression test.
- `unknown` — the reason could not be recovered (lost records, verbal
  decision, history predating the repo import). Maximum caution: list the most
  recent meaningful authors of the code as the people to ask before changing
  it.

## Do Not

- Do not run bare `git blame` or trust its first answer.
- Do not invent a plausible rationale when evidence is missing. Deletion
  decisions rest on this report; an invented reason is worse than none.
- Do not state a factual claim without citing its commit, PR, or issue.
- Do not classify a commit as noise on a message pattern alone without the
  diff check.

## Stop If

- No concrete target (file plus line range, code fragment, or SHA) can be
  identified. Ask for one instead of investigating without a subject.
- The noise loop hits its iteration cap. Report the layers peeled so far and
  rule `unknown`.

## Report

- The origin commit, and the noise commits peeled to reach it.
- Every claim with its cited commit, PR, or issue; unreachable evidence
  sources declared, never papered over.
- One verdict with a concrete disposition: keep, remove with the stated
  precautions, or ask the listed authors.
