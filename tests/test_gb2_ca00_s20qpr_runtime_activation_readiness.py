from __future__ import annotations

import json
from pathlib import Path

import run_gb2_s20qpr_runtime_activation_readiness as smoke
from test_nex_cx_retrieval_answer_support_runtime_readiness import _fixture


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    report, receipt, design = _fixture()
    report_path = tmp_path / "report.json"
    receipt_path = tmp_path / "receipt.json"
    design_path = tmp_path / "design.json"
    for path, value in (
        (report_path, report),
        (receipt_path, receipt),
        (design_path, design),
    ):
        path.write_text(json.dumps(value), encoding="utf-8")
    receipt_path.chmod(0o600)
    return report_path, receipt_path, design_path


def test_runner_is_opt_in_and_reads_receipt_without_external_calls(tmp_path) -> None:
    report, receipt, design = _files(tmp_path)
    assert smoke.run_gb2_s20qpr_runtime_activation_readiness({})["status"] == (
        "SKIPPED"
    )

    result = smoke.run_gb2_s20qpr_runtime_activation_readiness(
        {smoke.SMOKE_ENV: "1"},
        holdout_report_path=report,
        receipt_path=receipt,
        design_path=design,
    )

    assert result["status"] == "PASS"
    assert result["manifest"]["decision"] == (
        "READY_FOR_SHADOW_RUNTIME_INTEGRATION"
    )
    assert result["new_provider_calls"] == result["new_database_calls"] == 0
    assert "holdout_reexecution=prohibited" in smoke.summary_line(result)


def test_runner_fails_closed_for_missing_or_exposed_receipt(tmp_path) -> None:
    report, receipt, design = _files(tmp_path)
    receipt.chmod(0o644)
    result = smoke.run_gb2_s20qpr_runtime_activation_readiness(
        {smoke.SMOKE_ENV: "1"},
        holdout_report_path=report,
        receipt_path=receipt,
        design_path=design,
    )
    assert result["status"] == "FAIL"
    assert result["failure_type"] == "PermissionError"
    assert result["runtime_activation_permitted"] is False

    missing = smoke.run_gb2_s20qpr_runtime_activation_readiness(
        {smoke.SMOKE_ENV: "1"},
        holdout_report_path=tmp_path / "missing.json",
        receipt_path=receipt,
        design_path=design,
    )
    assert missing["status"] == "FAIL"


def test_load_summary_and_main(tmp_path, monkeypatch, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    try:
        smoke._load(invalid)
    except TypeError:
        pass
    else:
        raise AssertionError("non-object evidence was accepted")

    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line({"status": "FAIL", "failure_code": "bad"})
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpr_runtime_activation_readiness",
        lambda: {"status": "PASS", "manifest": {}},
    )
    output = tmp_path / "output.json"
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"
    assert "=pass" in capsys.readouterr().out
