# Slice 0869: AG audit evidence privacy and tamper runbook

## Goal

Freeze S87 privacy checks, tamper and failure evidence, and the operator response
sequence before closing the requirement.

## Failure Evidence

The executable evidence runner proves:

1. trusted event hashes produce a verified integrity report;
2. an event hash mismatch fails verification;
3. duplicate and missing event IDs are reported explicitly;
4. an orphan evidence export fails trace continuity;
5. repeated packaging produces the same manifest hash, package hash, and ID;
6. a valid package verifies without issues;
7. manifest mutation fails verification and returns no trusted package ID;
8. an attacker-controlled package ID is not reflected in verification output;
9. event or export source failures produce redacted degraded projections;
10. verification leaves the historical source event unchanged.

The runner scans every projected surface for database credentials, raw event
messages, raw export bodies, untrusted identifiers, and sensitive field names.

## Operator Runbook

1. Quarantine a hash-mismatched evidence set and compare only trusted hashes.
2. Requery duplicate or missing event IDs from the immutable event source using
   the same trace.
3. Resolve trace, request, and export correlation failures before packaging.
4. Reject a manifest-tampered package and retain only verification metadata.
5. Never echo submitted package payloads or untrusted package identifiers.
6. Restore both source stores before retrying a degraded read.
7. Never rewrite historical events to make an integrity report pass.
8. Confirm zero owned rows before rerunning the protected PostgreSQL smoke.
9. Continue canonical SHA-256 verification until external notarization is
   explicitly approved.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_audit_evidence_privacy_runbook_evidence.py \
  --summary
```

Expected summary:

```text
ag_audit_evidence_privacy_runbook=pass surfaces=12 privacy=True tamper=True runbook=True
```

```bash
./.venv/bin/pytest -q \
  tests/test_ag_audit_evidence_privacy_runbook_evidence.py \
  --cov=run_ag_audit_evidence_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing
```

## Evidence

```text
ag_audit_evidence_privacy_runbook=pass surfaces=12 privacy=True tamper=True runbook=True
```

- Privacy runner tests: `7 passed`.
- Privacy runner statement/branch coverage: `100% / 100%`.
- S87 focused tests: `116 passed`; all seven measured S87 modules remained at
  `100% / 100%` statement/branch coverage.
- Full regression: `5899 passed, 1 warning`.
- Statement coverage: `72733 / 73614` (`98.803216779417%`).
- Branch coverage: `17080 / 17730` (`96.333897349126%`).

The warning is the existing Starlette `TestClient` deprecation warning.
