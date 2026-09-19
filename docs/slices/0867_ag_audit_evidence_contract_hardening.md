# Slice 0867: AG audit evidence contract hardening

## Objective

Freeze the S87 package, verification, and operations surfaces as strict JSON
Schema and OpenAPI contracts before PostgreSQL evidence is collected.

## Contract Decisions

- `audit_evidence.v1.schema.json` defines strict package creation responses,
  verification responses, and operations projections.
- Package and manifest identifiers use lowercase SHA-256 patterns and a stable
  `ag-audit-package-<32 hex>` identifier.
- Package manifests contain exactly the integrity and correlation report
  references, safe export references, counts, and explicit redaction flags.
- Verification responses never echo the submitted package or an untrusted
  package ID.
- Operations export items reject raw evidence manifests and operator records.
- The unified dashboard keeps `audit_integrity` optional for older canonical
  fixtures, but validates the complete nested object strictly when present.
- The protected create, verify, and operations paths are published in the AG
  OpenAPI document.

## Fixtures

Three positive fixtures freeze package, verification, and operations shapes.
Three negative fixtures prove rejection of raw payload fields, untrusted package
IDs, and evidence-manifest leakage. All six are registered in the canonical
contract indexes.

## Verification

- Contract tree: `79 schemas`, `129 examples`, `92 negative examples`, and
  `7 OpenAPI` specifications passed.
- S87 focused tests: `94 passed` with statement/branch coverage of `100%` for
  the five audit-integrity runtime modules.
- Full regression: `5877 passed, 1 warning`.
- Statement coverage: `72468 / 73349` (`98.798892963776%`).
- Branch coverage: `17050 / 17700` (`96.327683615819%`).

The warning is the existing Starlette `TestClient` deprecation warning.
