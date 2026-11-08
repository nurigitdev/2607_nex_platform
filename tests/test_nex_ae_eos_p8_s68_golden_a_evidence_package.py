from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s68_golden_a_evidence_package as smoke


def _s67() -> dict[str, object]:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "actual_remote_provider": True,
        "nsl_release": {
            "source_revision": "1" * 40,
            "source_tree": "2" * 40,
            "source_tree_clean": True,
            "wheel_sha256": "sha256:" + "3" * 64,
        },
        "nsl_release_admission_hash": "sha256:" + "4" * 64,
        "migration_heads": {
            "nex-ae-api": "2507_ae_nsl_write_evidence",
            "nex-wc": "1006_wc_approval_foundation",
            "nex-oa": "1376_oa_trace_projection_index",
            "nex-eos": "2508_eos_operation_name_compatibility",
        },
        "business_operation_id": "a6aa226b-98f6-4c10-b9c1-c25fcf997b39",
        "nsl_execution_id": "p8-s53-golden-a-abc123",
        "approval_request_id": "cli-approval-abc123",
        "approval_work_item_id": "4ad36159-c314-4b72-9520-e128af1dd64e",
        "voucher_ref": "eos.voucher_draft:83da6b55-90e7-4bfd-a808-6f23c305e62a",
        "commit_state": "COMMITTED",
        "verification_status": "VERIFIED",
        "decision": {"business_mutation_count": 1},
        "residue_count": 0,
    }


def _full_gate() -> dict[str, object]:
    return {
        "status": "PASS",
        "gate_id": "full_regression",
        "evidence_digest": "5" * 64,
        "metrics": {
            "passed_test_count": 16700,
            "failed_test_count": 0,
            "skipped_test_count": 80,
            "statement_coverage": 96.8,
            "branch_coverage": 96.2,
        },
    }


def test_s68_is_explicitly_protected() -> None:
    assert smoke.run_p8_s68_golden_a_evidence_package({}, execute=False)[
        "status"
    ] == "SKIPPED"
    assert smoke.run_p8_s68_golden_a_evidence_package({}, execute=True)[
        "status"
    ] == "SKIPPED"


def test_s68_composes_safe_protected_and_full_gate_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.p8_s67, "run_p8_s67_golden_a_exactly_once", lambda *a, **k: _s67()
    )
    monkeypatch.setattr(smoke, "load_full_regression_evidence", lambda *a, **k: _full_gate())
    monkeypatch.setattr(smoke, "_git_identity", lambda _root: ("6" * 40, "7" * 40))

    result = smoke.run_p8_s68_golden_a_evidence_package(
        {smoke.SMOKE_ENV: "1"}, execute=True
    )

    assert result["status"] == "PASS", result
    assert result["gate"] == "P8.6_GOLDEN_A_CLOSED"
    assert result["outcome"] == {
        "commit_state": "COMMITTED",
        "verification_status": "VERIFIED",
        "business_mutation_count": 1,
        "residue_count": 0,
    }
    assert result["test_evidence"]["protected_run_id"].startswith("p8-s67:")
    assert result["test_evidence"]["full_gate_run_id"].startswith("full-gate:")


def test_s68_fails_closed_and_redacts_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = (
        "postgresql+psycopg://nex_ae_user:private@localhost/nex_ae_test"
    )
    failed = {"status": "FAIL"}
    monkeypatch.setattr(
        smoke.p8_s67, "run_p8_s67_golden_a_exactly_once", lambda *a, **k: failed
    )

    result = smoke.run_p8_s68_golden_a_evidence_package(
        {
            smoke.SMOKE_ENV: "1",
            smoke.p8_s67.p8_s65.AE_DATABASE_ENV: database_url,
        },
        execute=True,
    )

    assert result["status"] == "FAIL"
    assert "private" not in json.dumps(result)
    assert database_url not in json.dumps(result)


def test_s68_rejects_failed_full_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke.p8_s67, "run_p8_s67_golden_a_exactly_once", lambda *a, **k: _s67()
    )
    failed = _full_gate()
    failed["status"] = "FAIL"
    monkeypatch.setattr(smoke, "load_full_regression_evidence", lambda *a, **k: failed)

    result = smoke.run_p8_s68_golden_a_evidence_package(
        {smoke.SMOKE_ENV: "1"}, execute=True
    )

    assert result["status"] == "FAIL"
    assert result["detail"] == "Full Gate evidence did not pass"


def test_helpers_report_and_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    assert smoke._run_id("p8-s67", "sha256:" + "a" * 64) == (
        "p8-s67:" + "a" * 16
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("skipped")
    assert smoke.summary_line({"status": "FAIL"}).endswith("fail")
    passing = smoke.build_golden_a_evidence_package(
        platform={"commit": "1" * 40, "tree": "2" * 40},
        nsl_release={
            "source_revision": "3" * 40,
            "source_tree": "4" * 40,
            "wheel_sha256": "sha256:" + "5" * 64,
            "release_admission_hash": "sha256:" + "6" * 64,
        },
        migration_heads=_s67()["migration_heads"],
        test_evidence={
            "protected_gate_id": "P8-S67",
            "protected_run_id": "p8-s67:" + "7" * 16,
            "protected_evidence_digest": "sha256:" + "7" * 64,
            "actual_postgres": True,
            "actual_remote_provider": True,
            "full_gate_id": "full_regression",
            "full_gate_run_id": "full-gate:" + "8" * 16,
            "full_gate_evidence_digest": "sha256:" + "8" * 64,
            "passed_test_count": 10,
            "failed_test_count": 0,
            "skipped_test_count": 1,
            "statement_coverage": 96.0,
            "branch_coverage": 95.0,
        },
        lineage={
            key: _s67()[key]
            for key in (
                "business_operation_id",
                "nsl_execution_id",
                "approval_request_id",
                "approval_work_item_id",
                "voucher_ref",
            )
        },
        outcome={
            "commit_state": "COMMITTED",
            "verification_status": "VERIFIED",
            "business_mutation_count": 1,
            "residue_count": 0,
        },
    )
    assert "mutations=1" in smoke.summary_line(passing)
    report = tmp_path / "evidence.json"
    smoke.write_report(report, passing)
    assert json.loads(report.read_text(encoding="utf-8")) == passing
    assert not report.with_suffix(".json.tmp").exists()

    monkeypatch.setattr(
        smoke, "run_p8_s68_golden_a_evidence_package", lambda **kwargs: passing
    )
    assert smoke.main(["--summary", "--report", str(report)]) == 0
    assert "p8_s68_golden_a_evidence=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_p8_s68_golden_a_evidence_package",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


def test_git_identity_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout="1" * 40 + "\n"),
            SimpleNamespace(returncode=0, stdout="2" * 40 + "\n"),
        )
    )
    monkeypatch.setattr(smoke.subprocess, "run", lambda *a, **k: next(responses))
    assert smoke._git_identity(tmp_path) == ("1" * 40, "2" * 40)

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(ValueError, match="unavailable"):
        smoke._git_identity(tmp_path)
