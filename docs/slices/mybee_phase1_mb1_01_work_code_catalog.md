# MyBee Phase-1 MB1-01: Immutable FL Work-Code Catalog

## Scope

MB1-01 publishes the source-side D12 Project Governance catalog that EOS
`S1-05` will later import and admit. It does not create EOS tables, alter an
API, activate an NSL Tool, or change Project runtime behavior.

The first catalog revision contains exactly the frozen mandatory set:

| FL code | Name | Assignment vs execution |
| --- | --- | --- |
| `FL0012004` | 프로젝트 개설 | Project activation |
| `FL0012005` | 업무 구성 확정 | Configuration |
| `FL0012006` | PM 지정 | Configuration |
| `FL0012013` | 진행 보고 집계 | Required at assignment; executed during operations |
| `FL0012026` | 프로젝트 종결 | Required at assignment; executed during closure |

## Ownership And Admission

- `nex-mybee-ax` owns the domain-policy catalog.
- `nex-eos` remains Project and business-state SoR.
- `nex-wc` remains workflow owner where human approval is required.
- FL identifiers are business identifiers, not aliases for API operation IDs
  or NSL Tool IDs.
- Every consumer mapping is `DECLARED_NOT_BOUND`; S1-05 and the admitted Skill
  Pack own later bindings.
- Technical `ACTIVE` and MyBee `BUSINESS_READY` remain separate and neither is
  asserted by this Slice.

The source release is approved through
`SOURCE_AUTHORITY_CONTENT_DIGEST_V1`. Its shared canonical semantic digest
binds the version, owners, provenance, mandatory set, and entries. This is the
MB1-01 source mapping attestation; it is not represented as a cryptographic
runtime signature. Runtime signing is explicitly deferred to an admitted
Skill Pack so the repository never carries a fabricated signature or private
key.

`G-SRC-PDF` page-level reconciliation remains open. The catalog therefore
records `OPEN_G_SRC_PDF` and only claims the current SRS/PAD/source-audit
authority whose exact file hashes are embedded in the release.

## Verification

Final Slice evidence:

```text
focused MyBee regression: 40 passed
standard platform Slice Gate: 467 passed, 8 explicit protected skips
MyBee package statement coverage: 100.00% (threshold 95.00%)
MyBee package branch coverage: 100.00% (threshold 94.00%)
contract validation: PASS (233 schemas / 292 examples / 245 negative examples / 10 OpenAPI)
Golden transition audit: PASS
product dependency audit: PASS
package wheel: PASS; domain/work_codes.py included
database migrations: NONE
remote provider / PostgreSQL requirement: NONE
```

The protected skips are existing opt-in PostgreSQL topology, trust, migration,
and restart smokes. None is required by this source-only Slice and none is
reported as live acceptance.
