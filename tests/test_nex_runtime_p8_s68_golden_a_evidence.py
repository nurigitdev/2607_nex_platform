from __future__ import annotations

import json
from copy import deepcopy

import nex_runtime.golden_a_evidence as evidence
import pytest


def _parts() -> dict[str, dict[str, object]]:
    return {
        "platform": {"commit": "1" * 40, "tree": "2" * 40},
        "nsl_release": {
            "source_revision": "3" * 40,
            "source_tree": "4" * 40,
            "wheel_sha256": "sha256:" + "5" * 64,
            "release_admission_hash": "sha256:" + "6" * 64,
        },
        "migration_heads": {
            "nex-ae-api": "2507_ae_nsl_write_evidence",
            "nex-wc": "1006_wc_approval_foundation",
            "nex-oa": "1376_oa_trace_projection_index",
            "nex-eos": "2508_eos_operation_name_compatibility",
        },
        "test_evidence": {
            "protected_gate_id": "P8-S67",
            "protected_run_id": "p8-s67:" + "7" * 16,
            "protected_evidence_digest": "sha256:" + "7" * 64,
            "actual_postgres": True,
            "actual_remote_provider": True,
            "full_gate_id": "full_regression",
            "full_gate_run_id": "full-gate:" + "8" * 16,
            "full_gate_evidence_digest": "sha256:" + "8" * 64,
            "passed_test_count": 16700,
            "failed_test_count": 0,
            "skipped_test_count": 80,
            "statement_coverage": 96.8,
            "branch_coverage": 96.2,
        },
        "lineage": {
            "business_operation_id": "a6aa226b-98f6-4c10-b9c1-c25fcf997b39",
            "nsl_execution_id": "p8-s53-golden-a-abc123",
            "approval_request_id": "cli-approval-abc123",
            "approval_work_item_id": "4ad36159-c314-4b72-9520-e128af1dd64e",
            "voucher_ref": (
                "eos.voucher_draft:83da6b55-90e7-4bfd-a808-6f23c305e62a"
            ),
        },
        "outcome": {
            "commit_state": "COMMITTED",
            "verification_status": "VERIFIED",
            "business_mutation_count": 1,
            "residue_count": 0,
        },
    }


def _package() -> dict[str, object]:
    return evidence.build_golden_a_evidence_package(**_parts())


def test_builds_exact_digest_protected_metadata_only_package() -> None:
    package = _package()
    result = evidence.validate_golden_a_evidence_package(package)

    assert result["status"] == "PASS", result
    assert result["summary"] == {
        "check_count": 10,
        "passed_check_count": 10,
        "migration_head_count": 4,
        "business_mutation_count": 1,
        "residue_count": 0,
    }
    assert package["gate"] == "P8.6_GOLDEN_A_CLOSED"
    assert package["package_digest"].startswith("sha256:")
    serialized = str(package).lower()
    assert "postgresql" not in serialized
    assert "http://" not in serialized
    assert "payload" not in serialized


def test_sorted_json_round_trip_preserves_package_validity() -> None:
    restored = json.loads(json.dumps(_package(), sort_keys=True))

    result = evidence.validate_golden_a_evidence_package(restored)

    assert result["status"] == "PASS", result


@pytest.mark.parametrize(
    ("mutate", "failed"),
    (
        (lambda item: item.update(extra="drift"), "schema_exact"),
        (lambda item: item["platform"].update(commit="short"), "platform_identity_valid"),
        (lambda item: item["nsl_release"].update(wheel_sha256="wrong"), "nsl_release_valid"),
        (lambda item: item["migration_heads"].pop("nex-eos"), "migration_heads_exact"),
        (
            lambda item: item["test_evidence"].update(actual_postgres=False),
            "protected_test_evidence_valid",
        ),
        (
            lambda item: item["test_evidence"].update(branch_coverage=93.99),
            "full_gate_evidence_valid",
        ),
        (lambda item: item["lineage"].update(business_operation_id="bad"), "lineage_valid"),
        (lambda item: item["outcome"].update(residue_count=1), "outcome_closed"),
    ),
)
def test_validation_fails_closed_for_each_evidence_boundary(mutate, failed) -> None:
    package = deepcopy(_package())
    mutate(package)

    result = evidence.validate_golden_a_evidence_package(package)

    assert result["status"] == "FAIL"
    assert failed in result["failed_checks"]
    assert "package_digest_valid" in result["failed_checks"]


def test_privacy_and_digest_drift_are_rejected() -> None:
    package = deepcopy(_package())
    package["test_evidence"]["provider_endpoint"] = "https://private.invalid"

    result = evidence.validate_golden_a_evidence_package(package)

    assert result["status"] == "FAIL"
    assert result["privacy_violations"] == [
        "$.test_evidence.provider_endpoint"
    ]
    assert {"privacy_clean", "package_digest_valid"}.issubset(
        result["failed_checks"]
    )


def test_builder_rejects_invalid_package_and_helpers_cover_type_edges() -> None:
    parts = _parts()
    parts["outcome"]["business_mutation_count"] = True
    with pytest.raises(ValueError, match="outcome_closed"):
        evidence.build_golden_a_evidence_package(**parts)

    assert evidence.validate_golden_a_evidence_package([])["status"] == "FAIL"
    assert evidence._mapping([]) == {}
    assert evidence._uuid(None) is False
    assert evidence._uuid("not-a-uuid") is False
    assert evidence._positive_int(True) is False
    assert evidence._nonnegative_int(-1) is False
    assert evidence._minimum_number(True, 1.0) is False
    assert evidence._privacy_violations(
        [{"safe": "Bearer hidden"}, {"safe": "plain"}]
    ) == ["$[0].safe"]
