from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = (
    ROOT / "docs/mybee_phase1/closure/cp_m1_e2e_fx_01_evidence.v1.json"
)
REQUIRED_CHECKPOINTS = (
    "CP-M1-PA-WORK",
    "CP-M1-BUSINESS-PROOF",
    "CP-M1-JOURNAL",
    "CP-M1-PNL",
    "CP-M1-S8-02",
    "CP-M1-MB8-01",
    "CP-M1-E2E-FX-01",
)
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


def _evidence() -> dict[str, object]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_m1_closure_manifest_admits_all_seven_checkpoints() -> None:
    evidence = _evidence()
    checkpoints = evidence["checkpoints"]

    assert evidence["status"] == "PASS"
    assert evidence["milestone_scope"] == "M1_CHECKPOINT_ONLY"
    assert tuple(item["id"] for item in checkpoints) == REQUIRED_CHECKPOINTS
    assert all(item["status"] == "PASS" for item in checkpoints)
    assert all(item["evidence_refs"] for item in checkpoints)
    for item in checkpoints:
        for relative in item["evidence_refs"]:
            assert (ROOT / relative).is_file(), relative


def test_m1_closure_manifest_binds_redacted_exact_head_evidence() -> None:
    evidence = _evidence()

    assert REVISION.fullmatch(evidence["runtime_source_revision"])
    for artifact in evidence["evidence"].values():
        assert artifact["path"].startswith("reports/")
        assert SHA256.fullmatch(artifact["sha256"])
    assert evidence["secret_included"] is False
    assert evidence["token_value_included"] is False


def test_m1_closure_manifest_proves_public_product_journey() -> None:
    evidence = _evidence()
    execution = evidence["execution"]

    assert execution["platform_integrated"] is True
    assert execution["runtime_transition_fixture"] is False
    assert execution["manual_domain_transition"] is False
    assert execution["direct_runtime_transition_sql"] is False
    assert execution["actual_postgres"] is True
    assert execution["database_count"] == 8
    assert execution["migration_count"] == 210
    assert execution["actual_playwright"] is True
    assert execution["actual_remote_generation"] is True
    assert execution["provider"] == {
        "model": "Qwen3.5-9B",
        "revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
        "deployment_id": "dgx-qwen3-5-9b-9111",
        "reasoning_mode": "disabled",
    }
    assert execution["non_identical_transaction_count"] == 2
    assert execution["distinct_human_principal_count"] == 3
    assert execution["approval_decision_count"] == 6
    assert execution["immutable_journal_count"] == 2
    assert execution["allocation_batch_count"] == 2
    assert execution["pnl_projection_count"] == 4
    assert execution["agent_result_count"] == 2
    assert execution["wa_successful_job_count"] == 4
    assert execution["first_batch"]["unallocated_total"] == "0.0000"


def test_m1_closure_manifest_preserves_restart_and_m2_boundaries() -> None:
    evidence = _evidence()
    restart = evidence["restart_acceptance"]
    release = evidence["release_set"]
    quality = evidence["quality"]

    assert all(
        restart[name] is True
        for name in (
            "authoritative_result_recovered",
            "result_hash_stable",
            "business_refs_stable",
        )
    )
    assert restart["exactly_once_journal_count"] == 2
    assert restart["exactly_once_allocation_batch_count"] == 2
    assert restart["exactly_once_agent_result_count"] == 2
    assert release["image_count"] == release["manifest_count"] == 9
    assert release["non_root_image_count"] == 9
    assert SHA256.fullmatch(release["release_set_digest"])
    assert SHA256.fullmatch(release["ae_product_runtime_image_id"])
    assert quality["ae_statement_coverage_percent"] >= 95.0
    assert quality["ae_branch_coverage_percent"] >= 94.0
    assert evidence["cleanup"]["zero_residue"] is True
    assert evidence["cleanup"]["residue_service_ids"] == []
    assert {
        "S5-01",
        "S5-04",
        "S8-02_FULL",
        "S8-03_FULL",
        "S8-05",
        "MB8-01_FULL",
        "MB8-02",
    }.issubset(evidence["deferred_to_m2"])
