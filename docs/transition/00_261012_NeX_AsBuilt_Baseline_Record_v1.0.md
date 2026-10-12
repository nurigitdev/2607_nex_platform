# NeX As-Built Baseline Record v1.0

**Record Date:** 2026-10-12  
**Purpose:** NeX Platform v1.0 / NSL v0.1 As-Built analysis and v2.1 Frozen Architecture transition validation baseline

---

## 1. NeX Platform v1.0

- Repository: `nurigitdev/2607_nex_platform`
- Default branch: `master`
- Intended Git tag: `v1.0`
- Current baseline commit:
  - SHA: `ab7af0fc3b42225d1d71d20d517889d694a01c03`
  - Short SHA: `ab7af0f`
  - Commit: `Slice 1504: close S150 production release readiness`
  - Commit time: `2026-10-09T08:59:56Z`
- Baseline interpretation:
  - NeX Platform v1.0 implementation/release-readiness work is closed at S150.
  - The source records implementation completion separately from production deployment authorization.
  - Current release decision recorded by the source is `NO_GO`; this does **not** invalidate the implementation-complete As-Built baseline.
- Existing `v1.0` ref/tag check: **not found**

Recommended tag command:

```bash
git fetch origin
git checkout master
git pull --ff-only
git tag -a v1.0 ab7af0fc3b42225d1d71d20d517889d694a01c03 -m "NeX Platform v1.0 As-Built baseline"
git push origin v1.0
```

---

## 2. NSL v0.1

- Repository: `nurigitdev/2608_nsl`
- Default branch: `master`
- Intended Git tag: `v0.1`
- Current baseline commit:
  - SHA: `803f22aadc3946a48b05472c80b60fe11d9d9554`
  - Short SHA: `803f22a`
  - Commit: `ci: add NSL v0.1 quality gate`
  - Commit time: `2026-09-16T07:04:36Z`
- Baseline interpretation:
  - This commit adds the independent NSL v0.1 quality gate to the implemented v0.1 source baseline.
- Existing `v0.1` ref/tag check: **not found**

Recommended tag command:

```bash
git fetch origin
git checkout master
git pull --ff-only
git tag -a v0.1 803f22aadc3946a48b05472c80b60fe11d9d9554 -m "NSL v0.1 As-Built baseline"
git push origin v0.1
```

---

## 3. Baseline Rule

Until Git tags are created, all analysis must pin directly to the exact commit SHAs above.

After tags are created, verify:

```bash
git rev-parse v1.0
git rev-parse v0.1
```

Expected:

- `v1.0` -> `ab7af0fc3b42225d1d71d20d517889d694a01c03`
- `v0.1` -> `803f22aadc3946a48b05472c80b60fe11d9d9554`

No later `master` change shall silently move the As-Built analysis baseline.

---

## 4. Next Step

Proceed to **P1 — NeX Platform v1.0 As-Built Architecture Extraction** only after the baseline is considered fixed by SHA or by the intended tags above.
