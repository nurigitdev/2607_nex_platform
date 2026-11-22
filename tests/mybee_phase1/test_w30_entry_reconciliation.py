from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/transition/MyBee_Phase1"
DECISION_PATH = DOCS / "NeX_MyBee_W30_CA01_Entry_Decision_v1.0.json"
MATRIX_PATH = DOCS / "NeX_MyBee_Implementation_Slice_Plan_Execution_Matrix_v1.2.json"
CA02_PATH = (
    DOCS
    / "NeX_MyBee_W30_CA02_Project_Application_Code_Lifecycle_and_PA_Contract_Closure_v1.0.md"
)
MIGRATIONS = ROOT / "database/nex-eos/migrations"


def _decision() -> dict[str, object]:
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def _walk_packet(value: object, packet_id: str) -> dict[str, object]:
    if isinstance(value, dict):
        if value.get("packet_id") == packet_id:
            return value
        for child in value.values():
            try:
                return _walk_packet(child, packet_id)
            except LookupError:
                pass
    elif isinstance(value, list):
        for child in value:
            try:
                return _walk_packet(child, packet_id)
            except LookupError:
                pass
    raise LookupError(packet_id)


def test_w30_ca01_reading_order_and_decision_identity() -> None:
    readme = (DOCS / "README.md").read_text(encoding="utf-8")
    decision = _decision()

    assert "NeX_MyBee_W30_CA01_W20_to_W30_Entry_Reconciliation_v1.0.md" in readme
    assert DECISION_PATH.name in readme
    assert CA02_PATH.name in readme
    assert decision["schema_version"] == "nex.mybee.w30-ca01.entry-decision.v1"
    assert decision["status"] == "DESIGN_CLOSED_RUNTIME_ENTRY_CONDITIONAL"
    assert decision["w30_order"] == [
        "W30-S00",
        "S3-01",
        "S3-02",
        "S3-03",
        "MB3-01",
    ]


def test_w30_ca01_migration_reservations_follow_actual_inventory() -> None:
    versions = sorted(
        int(match.group(1))
        for path in MIGRATIONS.glob("*.sql")
        if (match := re.match(r"^(\d+)_", path.name))
    )
    decision = _decision()
    reservations = decision["migration_reservations"]

    reserved_versions = [item["version"] for item in reservations]
    assert reserved_versions == [
        "2530_eos_document_signoff_finalization",
        "2531_eos_voucher_candidate_v2",
    ]
    # CA01 is a design-time snapshot. W30-S00 consumed 2530 as reserved, while
    # CA02 consumed 2531-2533 and moved S3-01 to the next inventory slot, 2534.
    assert (MIGRATIONS / "2530_eos_document_signoff_finalization.sql").is_file()
    assert not (MIGRATIONS / "2531_eos_voucher_candidate_v2.sql").exists()
    ca02 = CA02_PATH.read_text(encoding="utf-8")
    assert "2531_eos_project_application_lifecycle.sql" in ca02
    assert "2532_eos_project_application_approval.sql" in ca02
    assert "2533_eos_mandatory_project_attribution.sql" in ca02
    manifest = json.loads(
        (ROOT / "docs/mybee_phase1/baselines/source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected = manifest["migration_heads"]["nex-eos"]
    assert versions[-1] == expected["version"]
    expected_path = ROOT / expected["path"]
    assert expected_path.is_file()
    assert expected_path.name.startswith(f"{expected['version']}_")


def test_w30_ca01_source_facts_match_current_provider_boundary() -> None:
    decision = _decision()
    facts = decision["source_facts"]
    scoped = (ROOT / "services/nex-eos/nex_eos/scoped_approvals.py").read_text(
        encoding="utf-8"
    )
    accounting = (ROOT / "services/nex-eos/nex_eos/accounting_approval.py").read_text(
        encoding="utf-8"
    )
    approved_api = (
        ROOT / "services/nex-eos/nex_eos/approved_document_api.py"
    ).read_text(encoding="utf-8")

    assert "DOCUMENT_SIGNOFF" in scoped
    assert "DOCUMENT_SIGNOFF cannot satisfy accounting approval" in accounting
    assert "@app.get(" in approved_api
    assert "@app.post(" not in approved_api
    assert facts["document_signoff_decision_is_rejected_by_accounting_service"] is True
    assert facts["approved_document_public_create_exists"] is False
    assert facts["voucher_candidate_v2_exists"] is False
    assert (ROOT / "services/nex-eos/nex_eos/voucher_candidates.py").exists()
    assert (ROOT / "docs/slices/mybee_phase1_s3_01_voucher_candidate_v2.md").exists()


def test_mb3_wave_label_is_normalized_by_delta_without_mutating_pinned_matrix() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    packet = _walk_packet(matrix, "MB3-01")
    decision = _decision()

    assert packet["wave"] == "W31"
    assert packet["dependencies"] == ["S3-01", "S3-02"]
    assert decision["wave_normalization"] == {
        "packet_id": "MB3-01",
        "old_wave": "W31",
        "canonical_wave": "W30",
    }


def test_w30_ca01_preserves_v1_and_forbids_posting_shortcuts() -> None:
    decision = _decision()
    boundaries = decision["runtime_boundaries"]
    prohibited = set(decision["mandatory_entry_slice"]["prohibited_shortcuts"])

    assert boundaries == {
        "w30_creates_posted_journal": False,
        "w30_changes_voucher_v1": False,
        "mybee_direct_sql_allowed": False,
        "remote_model_provider_required": False,
    }
    assert "SYNTHETIC_OR_UNRELATED_PROJECT" in prohibited
    assert "REUSE_ACCOUNTING_EVIDENCE_AS_BUSINESS_PROOF" in prohibited
    assert "MYBEE_DIRECT_EOS_OR_WC_DATABASE_WRITE" in prohibited
