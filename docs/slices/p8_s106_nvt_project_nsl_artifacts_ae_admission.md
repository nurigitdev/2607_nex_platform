# P8-S106: NVTProject NSL Artifacts and AE Admission

## Scope

P8-S106 binds the P8-S105 protected EOS NVTProject operations to exact NSL
artifacts and the AE project-operation planning boundary.

- `PROJECT.NVT_PROJECT.GET` and `PROJECT.NVT_PROJECT.LIST` are admitted READ
  skills.
- `PROJECT.NVT_PROJECT.CREATE` and `PROJECT.NVT_PROJECT.UPDATE` are admitted
  controlled WRITE skills.
- AE resolves NVTProject selectors only from tenant-scoped authoritative
  records. Exact project code is required; display-name matches require user
  confirmation.
- Model-proposed `nvt_project_id` and `nvt_project_ref` values remain authority
  fields and are rejected before binding.
- CREATE derives a deterministic NVTProject UUID from admitted intent state.
  UPDATE binds the current entity version and requires an explicit name or
  status change.
- No database migration or runtime wheel change is introduced by this Slice.

## NSL Source Admission

The source-backed artifact set was added to `nurigitdev/2608_nsl` at revision
`6ab16da5e8840a1387c4c2c3d6eeb933e54849d4`.

```text
read manifest  = sha256:56d2bbc035cd10c2d40fa84f4664e7c05ea8b70362b7a724df0a15dc4f8d0c01
write manifest = sha256:ae2a3d8ebf827aebc076418c7ba9075f895c24e084c40536b43b7ecbc9729057
read skills    = 5
write skills   = 6
```

The NSL repository Full Gate passed with `2327 passed` and total coverage
`98.95%`. Platform source-backed tests compile every admitted skill from the
exact revision and compare source and semantic digests with both manifests.

## AE Admission

The canonical project-operation set now contains eleven operations. The new
NVTProject bindings preserve the same fail-closed planning rules as Project
and Membership operations:

- tenant isolation and exact-code resolution;
- deterministic IDs and semantic admission hashes;
- bounded LIST pagination and `ACTIVE`/`INACTIVE` status validation;
- code conflict, ambiguity, missing authority, and invalid update rejection;
- immutable capability identity and model-authority denial;
- exact READ/WRITE artifact-set admission.

The admission contract adds the optional `eos.nvt_project` typed reference
without changing existing Project or Membership payloads.

## Regression Hardening

The legacy S110 acceptance audit used a broad `*s104_*closure.md` glob. The
new P8-S104 document exposed that this could conflate requirement namespaces.
The audit now recognizes only the canonical four-digit legacy Slice prefix,
and a regression test proves that a `p8_s104_*` document is ignored.

## Verification

- focused NSL source/admission/planning/audit regression: `63 passed`
- Ruff and `git diff --check`: passed
- contract validation: `199` schemas, `263` examples, `225` negative examples,
  and `9` OpenAPI documents
- AE Slice Gate: `5414 passed`, `44` expected protected skips
- combined statement coverage: `98.33%`
- combined branch coverage: `96.32%`
- project-operation planning statement coverage: `99.39%`
- project-operation planning branch coverage: `98.67%`
- intent-candidate generation statement coverage: `98.83%`
- intent-candidate generation branch coverage: `96.94%`

Actual multi-service PostgreSQL and live-provider acceptance remains assigned
to P8-S112. P8-S106 changes no persistent state.

## Exit

P8-S106 is complete. P8-S107 may add OA-backed employee batch resolution and
its required Checkpoint Gate on top of this exact NVTProject capability set.
