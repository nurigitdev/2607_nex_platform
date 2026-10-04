from __future__ import annotations

from pathlib import Path

import pytest

import run_platform_trust_operations_hardening as hardening


ROOT = Path(__file__).resolve().parents[1]


def test_platform_trust_operations_hardening_passes_canonical_repository() -> None:
    result = hardening.run_platform_trust_operations_hardening(ROOT)

    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 11,
        "passed_check_count": 11,
        "active_claim_service_count": 4,
        "contract_artifact_count": 6,
        "runbook_section_count": 8,
    }
    assert result["next_slice"] == "1341"


def test_hardening_fails_closed_when_contracts_and_runbook_are_missing(
    tmp_path: Path,
) -> None:
    result = hardening.run_platform_trust_operations_hardening(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "platform_trust_operations_hardening_failed"
    assert "contract_files_present" in result["issues"]
    assert "active_claim_contracts_complete" in result["issues"]
    assert "runbook_complete" in result["issues"]
    assert result["checks"]["privacy_evaluator_rejects_secret_keys"] is True
    assert result["checks"]["runbook_has_no_embedded_connection_or_secret"] is True


def test_read_and_privacy_probe_helpers(tmp_path: Path) -> None:
    target = tmp_path / "value.txt"
    target.write_text("value", encoding="utf-8")

    assert hardening._read(tmp_path, "value.txt") == "value"
    assert hardening._read(tmp_path, "missing.txt") == ""
    assert hardening._privacy_probe_rejected() is True


def test_summary_and_cli_exit_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passed = hardening.run_platform_trust_operations_hardening(ROOT)
    failed = {**passed, "status": "FAIL", "issues": ["drift"]}

    assert "checks=11/11" in hardening.summary_line(passed)
    assert hardening.summary_line(failed).endswith("issues=1")

    monkeypatch.setattr(
        hardening,
        "run_platform_trust_operations_hardening",
        lambda: passed,
    )
    assert hardening.main(["--summary"]) == 0
    assert "next=1341" in capsys.readouterr().out

    monkeypatch.setattr(
        hardening,
        "run_platform_trust_operations_hardening",
        lambda: failed,
    )
    assert hardening.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
