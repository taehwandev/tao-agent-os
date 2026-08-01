---
keyflow_id: sys_bulk_change_verification
status: review
type: ai-generated
---

# Bulk Change Verification

Use when applying one rule across many files at once — contract migrations,
mass renames, sliced conversions — with a script or repeated mechanical edits,
and when checking that the change and its verification actually looked at
something.

## Script Transforms Operate Line By Line

Do not transform code by character offset, brace matching, or multi-line
regex. One mismatched match shifts everything after it and can destroy the
indentation of a whole class while the file still compiles, so the damage is
invisible unless the diff is read.

- Iterate over the line array, find the opening and closing lines, and edit
  only the lines between them.
- Handle the single-line form and the multi-line form in separate branches.
  Nested parentheses in arguments silently defeat `[^()]*`-style regexes.
- After transforming, inspect the actual `git diff`. A processed-item count is
  not verification.

## Revert And Rewrite On Damaged Formatting

If a transform damaged formatting, revert that file
(`git checkout HEAD -- <file>`) and rewrite the transform. Do not try to
regex-"fix" the formatting in place; the fix pass also touches already-correct
blocks and makes the damage worse. Do not assume an auto-formatter can recover
the file unless the repo actually has one configured.

## Verify With Samples And Counts

- Sample real diff hunks in several transformed files, not only the files the
  script reports as touched.
- Grep for residual occurrences of the old pattern and report the match count.
  Expect zero, or explain each remaining match.
- Every count-based check must print how many items it compared and confirm
  the count is non-zero. A check that ran over an empty list passed by looking
  at nothing.

## Shell Word-Splitting Caveat

In shells that do not word-split unquoted variables (zsh, for example), a
newline-separated file list passed unquoted becomes a single argument:

```bash
paths=$(git diff --name-only A B)
git diff --quiet A B -- $paths   # one never-matching pathspec -> always "no difference"
for f in $LIST; do ...; done     # loop body runs once
```

Use `while IFS= read -r f; do ...; done < <(...)` or arrays instead. Combined
with the empty-list rule above, an unquoted pathspec can make a verification
step pass without comparing anything.

## Stop If

- The transform can only be expressed with character offsets, brace matching,
  or a multi-line regex; rewrite the approach as line-based branches instead.
- The diff shows shifted indentation or damaged formatting in any file; revert
  those files and rewrite the transform before continuing.
- A verification check cannot state how many items it compared.

## Verification

Before reporting a bulk change complete:

- the actual `git diff` was inspected, not only a processed-item count
- sampled diff hunks match the intended transform
- the residual grep count for the old pattern is zero, or every remaining
  match is explained
- each count-based check printed a non-zero compared-item count
- file lists were iterated with read-loops or arrays, not unquoted scalar
  expansion
