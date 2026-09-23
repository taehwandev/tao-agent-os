---
keyflow_id: sys_common_testing_final_check
status: stable
type: ai-generated
---

# Final Test Check

Use this compact contract for the final `tests` gate on ordinary code work.

1. Before editing, identify the nearest check that can falsify the requested
   behavior. Run that focused check after the change.
2. Choose one execution owner per check. Inspect the project orchestrator's
   plan first; use its runner when required and run only missing checks
   separately. Do not repeat checks on unchanged inputs. Broaden for a changed
   boundary, a failure, or an explicit project gate.
3. Record the exact check, its exit status or pass/fail result, and a count or
   selector that makes the result reproducible.
4. Reuse observed passes only with matching code, dependencies, configuration,
   toolchain, fixtures and external state. Commit/fast-forward alone needs no
   rerun for unchanged tests independent of location and revision. Honor project
   freshness and integration checks. Edits, conflict resolution, changed inputs,
   new findings or uncertain provenance invalidate affected results. Failed,
   incomplete or unobserved checks never pass by reuse.
   In original local `gate-batch` records, use `input_paths: []` for checks
   independent of commit metadata (all non-ignored files), or a complete file
   dependency list. Omit for revision-sensitive/uncertain checks. Cite reused
   results and provenance; never copy them as fresh evidence or add a reuse gate.
5. A failed required check blocks completion. Unrelated passing checks do not
   replace it.

For project-owned Python unittest checks, the optional `verify` hook combines
execution and tests-gate recording in one call:

```text
<TAO_LAUNCHER> verify --project <TARGET_REPO> --rules <TAO_ROOT> --test-directory tests --test-pattern 'test_owner*.py'
```

Use it instead of running that selection and then recording `gate-batch`.
It requires the current session's active run with a `tests` gate, records the
observed exit code and count, and refuses success for zero tests, timeout, or
changed project/rules inputs. An interrupted run leaves failed evidence rather
than retaining an older pass. Its result covers only the selected tests;
ignored artifacts, dependencies and external state still need the normal
scope judgment. It neither grants command authority nor replaces final review.
Other frameworks and project-mandated runners retain their existing execution
and evidence path. Do not rerun an already verified selection merely to adopt
this convenience command.

Load `current-guidance.md` only when choosing test boundaries, fixtures,
scenario coverage, failure classification, or another testing decision that
this final-check contract does not answer.
