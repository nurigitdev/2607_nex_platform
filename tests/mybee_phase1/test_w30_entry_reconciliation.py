from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/transition/MyBee_Phase1"
DECISION_PATH = DOCS / "NeX_MyBee_W30_CA01_Entry_Decision_v1.0.json"
MATRIX_PATH = DOCS / "NeX_MyBee_Implementation_Slice_Plan_Execution_Matrix_v1.2.json"
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

    assert versions[-1] == 2529
    assert [item["version"] for item in reservations] == [
        "2530_eos_document_signoff_finalization",
        "2531_eos_voucher_candidate_v2",
    ]
    assert not (MIGRATIONS / "2530_eos_document_signoff_finalization.sql").exists()
    assert not (MIGRATIONS / "2531_eos_voucher_candidate_v2.sql").exists()


def test_w30_ca01_source_facts_match_current_provider_boundary() -> None:
    decision = _decision()
    facts = decision["source_facts"]
    scoped = (
        ROOT / "services/nex-eos/nex_eos/scoped_approvals.py"
    ).read_text(encoding="utf-8")
    accounting = (
        ROOT / "services/nex-eos/nex_eos/accounting_approval.py"
    ).read_text(encoding="utf-8")
    approved_api = (
        ROOT / "services/nex-eos/nex_eos/approved_document_api.py"
    ).read_text(encoding="utf-8")

    assert "DOCUMENT_SIGNOFF" in scoped
    assert "DOCUMENT_SIGNOFF cannot satisfy accounting approval" in accounting
    assert '@app.get(' in approved_api
    assert '@app.post(' not in approved_api
    assert facts["document_signoff_decision_is_rejected_by_accounting_service"] is True
    assert facts["approved_document_public_create_exists"] is False
    assert not (ROOT / "services/nex-eos/nex_eos/voucher_candidates.py").exists()


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
