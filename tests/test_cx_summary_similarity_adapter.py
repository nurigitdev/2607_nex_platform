from __future__ import annotations

import runpy
import sys

import pytest

import run_cx_summary_similarity_adapter as smoke


def test_summary_similarity_adapter_smoke_passes() -> None:
    result = smoke.run_cx_summary_similarity_adapter()
    assert result["status"] == "PASS"
    assert result["check_count"] == 10
    assert result["failed_checks"] == []
    assert result["candidate_count"] == 1
    assert result["postgres_required"] is False
    assert result["remote_required"] is False
    assert all(result["checks"].values())


def test_summary_similarity_adapter_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_summary_similarity_adapter()
    assert smoke._format_summary(passing) == (
        "cx_summary_similarity_adapter=pass checks=10/10 candidates=1 "
        "postgres_required=False remote_required=False"
    )
    monkeypatch.setattr(sys, "argv", ["summary-similarity", "--summary"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("run_cx_summary_similarity_adapter", run_name="__main__")
    assert caught.value.code == 0
    assert "cx_summary_similarity_adapter=pass" in capsys.readouterr().out


def test_summary_similarity_adapter_main_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_summary_similarity_adapter",
        lambda: {
            "status": "FAIL",
            "check_count": 1,
            "failed_checks": ["owner"],
            "candidate_count": 0,
        },
    )
    monkeypatch.setattr(sys, "argv", ["summary-similarity"])
    assert smoke.main() == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
