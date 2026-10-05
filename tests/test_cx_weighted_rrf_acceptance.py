from __future__ import annotations

from pathlib import Path

import run_cx_weighted_rrf_acceptance as acceptance


def test_repository_weighted_rrf_acceptance_passes() -> None:
    result = acceptance.run_cx_weighted_rrf_acceptance()
    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["ranking_policy"] == {
        "policy_id": "weighted_rrf_vector_bm25_v1",
        "vector_weight": 0.7,
        "bm25_weight": 0.3,
        "rrf_k": 60,
    }


def test_weighted_rrf_acceptance_fails_closed_without_sources(tmp_path: Path) -> None:
    result = acceptance.run_cx_weighted_rrf_acceptance(tmp_path)
    assert result["status"] == "FAIL"
    assert result["issues"]


def test_summary_main_and_read_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.py"
    source.write_text("value", encoding="utf-8")
    assert acceptance._read_text(source) == "value"
    assert acceptance._read_text(tmp_path / "missing.py") == ""
    passing = {
        "status": "PASS",
        "ranking_policy": {"vector_weight": 0.7, "bm25_weight": 0.3, "rrf_k": 60},
        "next_slice": "1357",
    }
    assert acceptance.summary_line(passing) == (
        "cx_weighted_rrf_acceptance=pass weights=0.7/0.3 k=60 next=1357"
    )
    assert acceptance.summary_line({"status": "FAIL", "issues": [1]}) == (
        "cx_weighted_rrf_acceptance=fail issues=1"
    )
    monkeypatch.setattr(acceptance, "run_cx_weighted_rrf_acceptance", lambda: passing)
    assert acceptance.main(["--summary"]) == 0
    assert "next=1357" in capsys.readouterr().out
    assert acceptance.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        acceptance,
        "run_cx_weighted_rrf_acceptance",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert acceptance.main([]) == 1
