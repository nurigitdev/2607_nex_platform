from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE = (
    ROOT
    / "docs/transition/MyBee_Phase1/"
    "NeX_MyBee_M1_Final_AsBuilt_Baseline_and_W80_Handoff_v1.0.md"
)
MANIFEST = (
    ROOT
    / "docs/mybee_phase1/closure/"
    "w70_m1_final_asbuilt_w80_handoff.v1.json"
)
README = ROOT / "docs/transition/MyBee_Phase1/README.md"


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_m1_final_asbuilt_freezes_exact_product_and_release_baseline() -> None:
    manifest = _manifest()

    assert manifest["schema_version"] == (
        "mybee_w70_m1_final_asbuilt_w80_handoff.v1"
    )
    assert manifest["slice_id"] == "W70-M1-ASBUILT-01"
    assert manifest["status"] == "PASS"
    assert manifest["milestone_scope"] == "M1_CHECKPOINT_ONLY"
    assert manifest["repository"] == {
        "name": "nurigitdev/2607_nex_platform",
        "branch": "codex/mybee-phase1-implementation",
        "product_source_revision": (
            "773769bafa2ac6680d3a775f81902a2e69103909"
        ),
        "product_source_tree": "823878f3a7fb90cfef96820398dbbb8a41ed9ef8",
        "gate_evidence_revision": "17c56322",
        "live_runtime_revision": "8f59e29ba0a04fa372c14e1df0c28cfc37331594",
    }
    assert manifest["checkpoints"] == [
        "CP-M1-PA-WORK",
        "CP-M1-BUSINESS-PROOF",
        "CP-M1-JOURNAL",
        "CP-M1-PNL",
        "CP-M1-S8-02",
        "CP-M1-MB8-01",
        "CP-M1-E2E-FX-01",
    ]

    quality = manifest["quality"]
    assert quality["python_test_count"] == 24031
    assert quality["python_failure_count"] == 0
    assert quality["repository_statement_coverage_percent"] >= 96.0
    assert quality["repository_branch_coverage_percent"] >= 94.0
    assert quality["product_statement_coverage_percent"] >= 98.0
    assert quality["product_branch_coverage_percent"] >= 96.0

    release = manifest["release_set"]
    assert release["artifact_count"] == 9
    assert release["non_root_image_count"] == 9
    assert release["installed_process_count"] == 21
    assert release["registry_push_performed"] is False
    assert release["secret_included"] is False


def test_m1_final_asbuilt_preserves_migration_and_evidence_lineage() -> None:
    manifest = _manifest()
    migrations = manifest["migration_inventory"]

    assert sum(item["count"] for item in migrations.values()) == 210
    assert migrations["nex-eos"]["head"] == "2548_eos_pnl_privacy_guard"
    assert migrations["nex-wc"]["head"] == "1007_wc_assignment_dispatch_scan"
    assert migrations["nex-oa"]["head"] == "2519_oa_project_entitlement_inbox"

    for evidence_ref in manifest["evidence_refs"]:
        assert (ROOT / evidence_ref).is_file(), evidence_ref

    execution = manifest["execution"]
    assert execution["actual_postgres"] is True
    assert execution["actual_remote_generation"] is True
    assert execution["runtime_transition_fixture"] is False
    assert execution["direct_runtime_transition_sql"] is False
    assert execution["zero_residue"] is True
    assert manifest["secret_included"] is False
    assert manifest["token_value_included"] is False


def test_m1_final_asbuilt_keeps_m2_open_and_authorizes_only_w80_entry() -> None:
    manifest = _manifest()
    deferred = set(manifest["deferred_to_m2"])
    handoff = manifest["w80_handoff"]

    assert {
        "S5-01",
        "S5-02",
        "S5-03",
        "S5-04",
        "S8-02_FULL",
        "S8-03_FULL",
        "MB8-01_FULL",
        "MB8-02",
    } <= deferred
    assert handoff["status"] == "AUTHORIZED"
    assert handoff["entry_boundary"] == "W80-CA01"
    assert handoff["ordered_packets"] == ["S5-01", "S5-02", "S5-03", "S5-04"]
    assert handoff["direct_destructive_journal_mutation_allowed"] is False
    assert handoff["m1_invariants_must_be_preserved"] is True

    text = BASELINE.read_text(encoding="utf-8")
    for invariant in (
        "model output, cached",
        "PostedJournal is immutable GL truth",
        "UNKNOWN commit state",
        "Allocation conserves source amounts",
        "No direct cross-service database read or write",
        "M1 checkpoint acceptance does not imply M2 completion",
        "W80-CA01: M1-to-M2 Journal Lifecycle Entry Reconciliation",
        "W70 M1 FINAL AS-BUILT FROZEN",
    ):
        assert invariant in text


def test_mybee_readme_admits_final_asbuilt_as_last_m1_record() -> None:
    readme = README.read_text(encoding="utf-8")

    assert (
        "NeX_MyBee_M1_Final_AsBuilt_Baseline_and_W80_Handoff_v1.0.md"
        in readme
    )
    assert "W70 M1 FINAL AS-BUILT FROZEN" in readme
    assert "W80-CA01" in readme
