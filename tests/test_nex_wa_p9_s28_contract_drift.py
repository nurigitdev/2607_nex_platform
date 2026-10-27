from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.wa_source_projections import WORK_SOURCE_READ_SCOPE as AE_SOURCE_SCOPE
from nex_eos.wa_project_verification import EOS_PROJECT_VERIFY_SCOPE
from nex_oa.subject_verification import OA_SUBJECT_VERIFY_SCOPE
from nex_runtime import DEFAULT_SERVICE_SCOPE
from nex_wa import OA_SUBJECT_VERIFY_SCOPE as WA_OA_SUBJECT_VERIFY_SCOPE
from nex_wa.agent_result_source import (
    EOS_PROJECT_VERIFY_SCOPE as WA_EOS_PROJECT_VERIFY_SCOPE,
    WORK_SOURCE_READ_SCOPE as WA_SOURCE_SCOPE,
)
from nex_wa.intake import WA_EVIDENCE_INGEST_SCOPE
from nex_wc.work_result_source_projection import WORK_SOURCE_READ_SCOPE as WC_SOURCE_SCOPE

ROOT = Path(__file__).resolve().parents[1]

SOURCE_CONTRACTS = (
    (
        "nex-ae-api",
        "WaAgentResultSourceProjection",
        "nex_ae_api/wa_agent_result_source_projection.v1.schema.json",
        "wa_agent_result_source_projection.acknowledged.json",
        "wa_agent_result_source_projection.raw_result.json",
    ),
    (
        "nex-ae-api",
        "WaArtifactSourceProjection",
        "nex_ae_api/wa_artifact_source_projection.v1.schema.json",
        "wa_artifact_source_projection.ready.json",
        "wa_artifact_source_projection.raw_bytes.json",
    ),
    (
        "nex-wc",
        "WaWorkResultSourceProjection",
        "nex_wc/wa_work_result_source_projection.v1.schema.json",
        "wa_work_result_source_projection.valid.json",
        "wa_work_result_source_projection.raw_payload.json",
    ),
    (
        "nex-oa",
        "SubjectVerification",
        "nex_oa/subject_verification.v1.schema.json",
        "oa_subject_verification.valid.json",
        None,
    ),
    (
        "nex-eos",
        "ProjectVerification",
        "nex_eos/project_verification.v1.schema.json",
        "eos_project_verification.valid.json",
        "eos_project_verification.project_name_leak.json",
    ),
    (
        "nex-eos",
        "ProjectMembershipVerification",
        "nex_eos/project_membership_verification.v1.schema.json",
        "eos_project_membership_verification.valid.json",
        "eos_project_membership_verification.subject_name_leak.json",
    ),
)

ROUTE_PARITY = (
    (
        "nex-wa",
        "/internal/v1/evidence-intake",
        "post",
        "nex-ae-api",
        (DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_INGEST_SCOPE),
    ),
    *(
        ("nex-ae-api", path, "get", "nex-wa", (DEFAULT_SERVICE_SCOPE, AE_SOURCE_SCOPE))
        for path in (
            "/internal/v1/wa-sources/agent-results",
            "/internal/v1/wa-sources/agent-results/{result_id}",
            "/internal/v1/wa-sources/artifacts",
            "/internal/v1/wa-sources/artifacts/{artifact_id}/versions/{artifact_version_id}",
        )
    ),
    *(
        ("nex-wc", path, "get", "nex-wa", (DEFAULT_SERVICE_SCOPE, WC_SOURCE_SCOPE))
        for path in (
            "/internal/v1/wa-sources/work-results/{result_id}",
            "/internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}",
        )
    ),
    (
        "nex-oa",
        "/internal/v1/identity/subjects:verify-batch",
        "post",
        "nex-wa",
        (DEFAULT_SERVICE_SCOPE, OA_SUBJECT_VERIFY_SCOPE),
    ),
    *(
        ("nex-eos", path, "post", "nex-wa", (DEFAULT_SERVICE_SCOPE, EOS_PROJECT_VERIFY_SCOPE))
        for path in (
            "/internal/v1/projects:verify-batch",
            "/internal/v1/project-memberships:verify-at",
        )
    ),
)

NEGATIVE_REGRESSION_MATRIX = {
    "unsupported source": (
        "tests/test_nex_wa_p9_s06_intake_contracts.py",
        "test_non_external_source_is_rejected",
    ),
    "source hash mismatch": (
        "tests/test_nex_wa_p9_s17_agent_result_admission.py",
        "test_identity_drift_and_project_denial_fail_closed",
    ),
    "same identity/different hash": (
        "tests/test_nex_wa_p9_s07_intake_api.py",
        "test_duplicate_enqueue_reuses_job_and_hash_conflict_is_rejected",
    ),
    "cross-tenant": (
        "tests/test_nex_wa_p9_s20_privacy_and_correction.py",
        "test_source_identity_lookup_is_tenant_and_revision_scoped",
    ),
    "unknown/inactive Human": (
        "tests/test_nex_wa_p9_s19_human_artifact_admission.py",
        "test_missing_or_inactive_owner_is_denied",
    ),
    "CA/PA/EA missing Project/Claim": (
        "tests/test_nex_wa_p9_s17_agent_result_admission.py",
        "test_unknown_or_malformed_authority_profile_fails_closed",
    ),
    "IA Project spoof": (
        "tests/test_nex_wa_p9_s17_agent_result_admission.py",
        "test_unknown_or_malformed_authority_profile_fails_closed",
    ),
    "Artifact not READY": (
        "tests/test_ae_p9_s12_artifact_projection.py",
        "test_projection_rejects_non_admissible_or_inconsistent_version",
    ),
    "Artifact version mismatch": (
        "tests/test_ae_p9_s12_artifact_projection.py",
        "test_exact_version_mismatch_is_not_found",
    ),
    "WC lineage mismatch": (
        "tests/test_nex_wa_p9_s18_wc_supporting_resolution.py",
        "test_wc_lineage_mismatch_fails_closed",
    ),
    "pre-ACK AgentResult": (
        "tests/test_nex_wa_p9_s17_agent_result_admission.py",
        "test_incomplete_result_is_typed_retry_and_never_admitted",
    ),
    "duplicate logical Agent work": (
        "tests/test_nex_wa_p9_s18_wc_supporting_resolution.py",
        "test_same_work_result_replay_keeps_exact_semantics",
    ),
    "stale worker settlement": (
        "tests/test_nex_wa_p9_s09_job_recovery.py",
        "test_stale_requeue_fences_old_worker_and_new_owner_completes",
    ),
    "raw payload": (
        "tests/test_nex_wa_p9_s06_intake_contracts.py",
        "test_raw_or_sensitive_payload_fields_are_rejected",
    ),
    "wrong intake scope": (
        "tests/test_nex_wa_p9_s07_intake_api.py",
        "test_service_authorization_is_fail_closed",
    ),
    "basic reader requesting detail": (
        "tests/test_nex_wa_p9_s20_privacy_and_correction.py",
        "test_basic_detail_and_audit_scopes_are_separated",
    ),
    "non-WA source projection caller": (
        "tests/test_ae_p9_s11_agent_result_projection.py",
        "test_route_fails_closed_for_auth_scope_caller_and_tenant",
    ),
    "unknown autonomous authority profile": (
        "tests/test_nex_wa_p9_s17_agent_result_admission.py",
        "test_unknown_or_malformed_authority_profile_fails_closed",
    ),
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _openapi(service_id: str):
    return yaml.safe_load(
        (ROOT / f"contracts/openapi/{service_id}.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )


def test_all_source_contracts_link_canonical_schema_and_validate_examples() -> None:
    for service_id, component, schema_path, positive, negative in SOURCE_CONTRACTS:
        document = _openapi(service_id)
        component_schema = document["components"]["schemas"][component]
        assert component_schema["x-nex-canonical-json-schema"] == (
            f"schemas/service/{schema_path}"
        )
        schema = _json(ROOT / f"contracts/schemas/service/{schema_path}")
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        assert list(
            validator.iter_errors(
                _json(ROOT / f"contracts/examples/service/{positive}")
            )
        ) == []
        if negative is not None:
            errors = list(
                validator.iter_errors(
                    _json(ROOT / f"contracts/tests/negative/service/{negative}")
                )
            )
            assert errors, negative


@pytest.mark.parametrize(
    ("service_id", "path", "method", "caller", "scopes"),
    ROUTE_PARITY,
)
def test_source_route_caller_and_scope_parity(
    service_id, path, method, caller, scopes
) -> None:
    operation = _openapi(service_id)["paths"][path][method]
    assert operation["x-nex-required-caller"] == caller
    assert tuple(operation["x-nex-required-scopes"]) == scopes


def test_consumer_scope_constants_match_producer_authority_contracts() -> None:
    assert WA_SOURCE_SCOPE == AE_SOURCE_SCOPE == WC_SOURCE_SCOPE == "work:source:read"
    assert WA_OA_SUBJECT_VERIFY_SCOPE == OA_SUBJECT_VERIFY_SCOPE
    assert WA_EOS_PROJECT_VERIFY_SCOPE == EOS_PROJECT_VERIFY_SCOPE


def test_negative_closure_matrix_is_complete_and_backed_by_regression() -> None:
    assert len(NEGATIVE_REGRESSION_MATRIX) == 18
    for test_path, function_name in NEGATIVE_REGRESSION_MATRIX.values():
        tree = ast.parse((ROOT / test_path).read_text(encoding="utf-8"))
        functions = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        assert function_name in functions, f"missing negative evidence: {function_name}"
