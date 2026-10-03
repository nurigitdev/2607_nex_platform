from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_oa.federated_auth_boundary import (
    S129_AG_SAFE_CLAIMS,
    S129_FEDERATED_AUTH_AG_BOUNDARY,
    S129_ID_TOKEN_ALGORITHMS,
    S129_OA_TABLES,
    S129_PROTOCOLS,
    federation_responsibility,
    validate_federated_auth_ag_boundary,
)
import run_oa_federated_auth_ag_boundary as runner


def test_s129_boundary_freezes_federated_auth_and_ag_integration() -> None:
    boundary = S129_FEDERATED_AUTH_AG_BOUNDARY

    assert validate_federated_auth_ag_boundary(boundary.to_wire()) == ()
    assert boundary.protocols == S129_PROTOCOLS
    assert boundary.id_token_algorithms == S129_ID_TOKEN_ALGORITHMS
    assert boundary.ag_safe_claims == S129_AG_SAFE_CLAIMS
    assert boundary.oa_tables == S129_OA_TABLES
    assert boundary.external_identity_linking == "PREPROVISIONED_EXACT_SUBJECT"
    assert boundary.deferred_protocols == ("SAML_2_0",)
    assert boundary.actual_postgres_smoke_slice == "1290"
    assert boundary.checkpoint_slice == "1286"
    assert boundary.full_gate_slice == "1291"
    assert boundary.slice_order == tuple(str(number) for number in range(1282, 1292))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("owner", "nex-ag", "owner_invalid"),
        ("consumer_service", "nex-ae-api", "consumer_service_invalid"),
        ("protocols", ("SAML_2_0",), "protocols_invalid"),
        ("id_token_algorithms", ("HS256",), "id_token_algorithms_invalid"),
        ("automatic_email_linking_allowed", True, "automatic_email_linking_allowed_must_be_false"),
        ("automatic_employee_id_linking_allowed", True, "automatic_employee_id_linking_allowed_must_be_false"),
        ("external_token_forwarding_allowed", True, "external_token_forwarding_allowed_must_be_false"),
        ("ag_direct_idp_validation_allowed", True, "ag_direct_idp_validation_allowed_must_be_false"),
        ("cross_service_database_reads_allowed", True, "cross_service_database_reads_allowed_must_be_false"),
        ("provider_secrets_persisted", True, "provider_secrets_persisted_must_be_false"),
        ("live_external_idp_required", True, "live_external_idp_required_must_be_false"),
        ("oa_session_issuance_required", False, "oa_session_issuance_required_must_be_true"),
        ("ag_admin_role_required", False, "ag_admin_role_required_must_be_true"),
        ("protected_loopback_smoke_required", False, "protected_loopback_smoke_required_must_be_true"),
        ("ag_safe_claims", (), "ag_safe_claims_invalid"),
        ("oa_tables", (), "oa_tables_invalid"),
        ("deferred_protocols", (), "deferred_protocols_invalid"),
        ("slice_order", (), "slice_order_invalid"),
    ),
)
def test_boundary_rejects_security_drift(
    field: str,
    value: object,
    error: str,
) -> None:
    payload = replace(
        S129_FEDERATED_AUTH_AG_BOUNDARY,
        **{field: value},
    ).to_wire()

    assert error in validate_federated_auth_ag_boundary(payload)


def test_boundary_reports_missing_fields_and_responsibilities() -> None:
    errors = validate_federated_auth_ag_boundary({})

    assert "field_missing:owner" in errors
    assert federation_responsibility("nex-oa") == (
        "identity_provider_trust_and_internal_session_authority"
    )
    assert federation_responsibility("nex-ag") == (
        "oa_normalized_operator_context_consumer"
    )
    assert federation_responsibility("external-idp") == "primary_user_authentication"
    assert federation_responsibility("unknown") is None


def test_repository_boundary_audit_passes() -> None:
    evidence = runner.run_oa_federated_auth_ag_boundary()

    assert evidence["status"] == "PASS"
    assert evidence["issues"] == []
    assert all(evidence["checks"].values())
    assert max(evidence["table_name_lengths"].values()) <= 30
    assert evidence["next_slice"] == "1283"


def test_boundary_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    evidence = runner.run_oa_federated_auth_ag_boundary(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "oa_federated_auth_ag_boundary_failed"
    assert evidence["checks"]["required_evidence_present"] is False
    assert len(evidence["issues"]) == len(runner.REQUIRED_EVIDENCE)
    assert evidence["next_slice"] == "blocked"


def test_boundary_runner_helpers_and_cli(monkeypatch, capsys, tmp_path: Path) -> None:
    assert runner._read_text(tmp_path / "missing") == ""
    passing = runner.run_oa_federated_auth_ag_boundary()
    assert runner.summary_line(passing) == (
        "oa_federated_auth_ag_boundary=pass checks=10/10 tables=2 next=1283"
    )
    monkeypatch.setattr(runner, "run_oa_federated_auth_ag_boundary", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1283" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_federated_auth_ag_boundary",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
