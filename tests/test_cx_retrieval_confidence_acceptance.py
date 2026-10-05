from __future__ import annotations

from pathlib import Path

import run_cx_retrieval_confidence_acceptance as acceptance


def test_repository_retrieval_confidence_acceptance_passes() -> None:
    result = acceptance.run_cx_retrieval_confidence_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["confidence_policy"] == {
        "policy_id": "cx_retrieval_confidence_v1",
        "low_confidence_threshold": 0.2,
        "threshold_inclusive": True,
        "no_evidence_behavior": "NO_ANSWER",
        "below_threshold_behavior": "LOW_CONFIDENCE",
    }


def test_retrieval_confidence_acceptance_fails_closed_without_sources(
    tmp_path: Path,
) -> None:
    result = acceptance.run_cx_retrieval_confidence_acceptance(tmp_path)
    assert result["status"] == "FAIL"
    assert result["issues"]


def test_summary_main_and_read_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.py"
    source.write_text("value", encoding="utf-8")
    assert acceptance._read_text(source) == "value"
    assert acceptance._read_text(tmp_path / "missing.py") == ""
    passing = {
        "status": "PASS",
        "confidence_policy": {
            "policy_id": "cx_retrieval_confidence_v1",
            "low_confidence_threshold": 0.2,
        },
        "next_slice": "1358",
    }
    assert acceptance.summary_line(passing) == (
        "cx_retrieval_confidence_acceptance=pass "
        "policy=cx_retrieval_confidence_v1 threshold=0.2 next=1358"
    )
    assert acceptance.summary_line({"status": "FAIL", "issues": [1]}) == (
        "cx_retrieval_confidence_acceptance=fail issues=1"
    )
    monkeypatch.setattr(
        acceptance,
        "run_cx_retrieval_confidence_acceptance",
        lambda: passing,
    )
    assert acceptance.main(["--summary"]) == 0
    assert "next=1358" in capsys.readouterr().out
    assert acceptance.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        acceptance,
        "run_cx_retrieval_confidence_acceptance",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert acceptance.main([]) == 1
