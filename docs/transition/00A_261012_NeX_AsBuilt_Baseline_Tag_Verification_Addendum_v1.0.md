# NeX As-Built Baseline Tag Verification Addendum v1.0

**Verification Date:** 2026-10-12
**Repository:** `nurigitdev/2607_nex_platform`
**Purpose:** Record the tag state created after the historical baseline record
without rewriting that record.

## 1. Platform v1.0 Verification

The annotated Git tag now exists:

```text
tag name:        v1.0
tag object:      a906bcbd27868a2a38287c00b8a46f9122677ae8
peeled commit:   ab7af0fc3b42225d1d71d20d517889d694a01c03
subject:         NeX Platform v1.0 As-Built baseline
tag date:        2026-10-12 09:01:36 +0900
```

The peeled commit exactly matches the Platform baseline commit recorded in
`00_261012_NeX_AsBuilt_Baseline_Record_v1.0.md`.

Verification commands:

```bash
git cat-file -t v1.0
git rev-parse v1.0
git rev-parse 'v1.0^{commit}'
git show -s --format='%H %s' 'v1.0^{commit}'
```

Expected commit:

```text
ab7af0fc3b42225d1d71d20d517889d694a01c03
```

## 2. Historical Record Treatment

The earlier statement that the tag was not found was accurate at the time of
the original baseline check. It remains unchanged as historical evidence.

This addendum is the current authoritative tag-verification status for the P4
transition branch.

## 3. NSL v0.1 Boundary

The NSL v0.1 repository is a separate repository and its tag was not verified
by this Platform-workspace addendum. Its transition baseline remains pinned to
the recorded commit:

```text
803f22aadc3946a48b05472c80b60fe11d9d9554
```

NSL tag verification shall be repeated in the NSL repository before P5 begins.

## 4. Frozen Integrity

This addendum does not modify any file under `docs/frozen/v2.1/` and does not
move or reinterpret the v1.0 baseline commit.
