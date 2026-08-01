---
keyflow_id: sys_release_versioning
status: stable
type: human-reviewed-needed
---

# Release Versioning

Use when choosing, changing, reviewing, tagging, or documenting a release,
deployment, package, app, build, or artifact version.

## Default

Versioning is an artifact-local contract. Do not force one calendar scheme
across unrelated projects. Do choose one scheme for each released artifact,
document it in the repo-local release instructions, and keep it stable.

The shared default is:

- Use SemVer for libraries, SDKs, APIs, plugins, generated clients, and packages
  where compatibility expectations matter.
- Use weekly CalVer `YY.WW.N` for date-based release tags and operational
  artifacts: two-digit year, ISO week, and a release count that starts at `1`
  for each week.
- Use monthly CalVer only when the repo-local release contract explicitly says
  the release unit is month-based.

## Supported Schemes

### SemVer

Use `MAJOR.MINOR.PATCH` when consumers need compatibility signals.

```text
2.4.7
2.5.0-rc.1
```

- Increment `MAJOR` for breaking changes.
- Increment `MINOR` for backward-compatible features.
- Increment `PATCH` for backward-compatible fixes.
- Prefer SemVer when package managers, app stores, or dependency resolvers
  expect SemVer semantics.

### Monthly CalVer

Use `YY.MM.N` only when the repo-local release contract says releases are
organized by month.

```text
26.05.1
26.05.2
26.06.1
```

- `YY` is the two-digit year. Do not use a four-digit year.
- `MM` is the release month.
- `N` starts at `1` each month and increments for each released artifact or
  production deployment, as defined by the repo.
- Do not use monthly CalVer just because a calendar date is available; the
  shared date-based default for tags is weekly CalVer `YY.WW.N`.

### Weekly CalVer

Use `YY.WW.N` for date-based release tags unless the repo-local release
contract explicitly documents another scheme.

```text
26.21.1
26.21.2
26.22.1
```

- `YY` is the two-digit year. Do not use `YYYY.WW.N`, `YYYY.MM.N`, or any
  four-digit calendar year in a release tag.
- `WW` should be the ISO week unless the repo explicitly documents another
  calendar.
- `N` starts at `1` each week and increments for each released artifact or
  production deployment, as defined by the repo.
- `N` must not start at `0`, and it should not be zero-padded unless the
  repo-local release contract explicitly requires padding.
- Document the timezone used to decide the release week.

## Required Repo-Local Contract

Every repo that uses calendar or custom versioning must document:

- scheme name: `semver`, `calver-monthly`, `calver-weekly`, or custom
- pattern and examples
- timezone or calendar source for date-based versions
- whether `N` counts published artifacts, production deployments, or public
  release attempts
- reset rule for `N`
- tag prefix, such as `v26.21.1`, and whether package metadata omits `v`
- prerelease format, such as `26.05.1-rc.1`
- build metadata or monotonic build number when stores or platforms require it

## Rules

- Do not mix `YY.MM.N` and `YY.WW.N` for the same artifact.
- Do not use four-digit years for date-based release tags. `2026.27.1` and
  `v2026.27.1` are wrong when the scheme is CalVer; use `26.27.1` or
  `v26.27.1`.
- Do not start the release count at `0`; the first released artifact for a week
  or month is `.1`.
- Do not switch schemes without a migration note and release owner approval.
- Do not infer month versus week from shape alone; read the repo-local contract.
- Use UTC for date-based versions unless repo-local release policy names another
  timezone.
- Decide whether the date comes from release cut, artifact publication, or
  production deployment, and keep that rule stable.
- Do not count failed builds, failed deploy attempts, or unpublished artifacts
  unless the repo explicitly says deployment attempts are the release unit.
- Keep package version, tag, artifact name, release notes, and deployment record
  consistent.
- If a SemVer-only tool rejects zero-padded date fields, use SemVer or a
  tool-compatible documented variant instead of forcing CalVer.

## Tag-Time Guards

When the repo tracks the build version in a version file or manifest, that
tracked file is the single source of truth. A release tag records a release
point; it never changes the build version. Run these guards, in order, before
creating a release tag, and block the tag when any guard fails:

1. Validate the tag against the scheme's strict format regex before any other
   check; this catches truncated or over-long versions such as `v3.1` or
   `3.1.0.0`.
2. Refuse computed bump arguments (`major`/`minor`/`patch`) at tag time.
   Version bumps happen only as a reviewed file-change commit before tagging;
   require the explicit version the tracked version source already carries.
3. Block the tag unless the tag version equals the tracked version at the
   target commit.
4. Monotonic guard: the new version must sort strictly above the latest
   existing tag under the scheme's ordering. Equal or lower is blocked to
   prevent version regressions in stores, package registries, and clients.

## Examples

Use monthly CalVer:

```text
scheme: calver-monthly
pattern: YY.MM.N
timezone: UTC
release unit: production deployment
example: v26.05.1
```

Use weekly CalVer:

```text
scheme: calver-weekly
pattern: YY.WW.N
calendar: ISO week
timezone: UTC
release unit: weekly release train artifact
example: v26.21.1
```

Use SemVer:

```text
scheme: semver
pattern: MAJOR.MINOR.PATCH
release unit: published package
example: v2.4.7
```

## Stop If

- The artifact, package, app display version, build number, tag, and deployment
  id are being treated as the same thing but the platform distinguishes them.
- A date-based release tag uses a four-digit year, an unspecified week/month
  basis, or a release count below `1`.
- The repo already uses a different scheme and no migration approval exists.
- The version would collide with an existing tag, artifact, package, or
  deployment record.
- Tooling rejects the chosen version format.
