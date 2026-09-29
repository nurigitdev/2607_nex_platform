from __future__ import annotations

from pathlib import Path

from nex_mo.catalog_config_audit import (
    DRIFT_PROBES,
    DriftProbe,
    _inspect_probe,
    build_mo_catalog_config_drift_audit,
)
import run_mo_catalog_config_drift_audit as runner


def test_repository_catalog_drift_is_classified() -> None:
    result = build_mo_catalog_config_drift_audit()

    assert result["status"] == "PASS"
    assert result["catalog_readiness"] == "DRIFT_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "profile_count": 5,
        "selected_profile_count": 3,
        "drift_count": 4,
        "high_risk_count": 0,
        "evidence_issue_count": 0,
    }
    assert result["current_defaults"]["selected_profiles"] == {
        "embedding": "Qwen3-Embedding-4B",
        "reranking": "Qwen3-Reranker-4B",
        "generation": "Qwen3.5-4B",
    }
    assert [item["priority"] for item in result["ordered_remediation"]] == ["P1", "P2"]


def test_audit_fails_closed_when_evidence_or_inventory_is_incomplete(
    tmp_path: Path,
) -> None:
    missing = DriftProbe(
        "missing",
        "missing.py",
        "token",
        "HIGH",
        "privacy",
        "1106",
    )

    result = build_mo_catalog_config_drift_audit(tmp_path, probes=(missing,))

    assert result["status"] == "FAIL"
    assert result["catalog_readiness"] == "BLOCKED"
    assert result["checks"]["drift_inventory_complete"] is False
    assert result["checks"]["drift_evidence_present"] is False
    assert result["issues"] == [
        {
            "category": "drift_evidence_missing",
            "finding_id": "missing",
            "path": "missing.py",
        }
    ]


def test_probe_inspection_covers_present_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "probe.py"
    path.write_text("expected token\n", encoding="utf-8")
    probe = DriftProbe("probe", "probe.py", "expected", "LOW", "test", "S112")

    assert _inspect_probe(tmp_path, probe)["evidence_present"] is True
    assert _inspect_probe(
        tmp_path,
        DriftProbe("missing", "probe.py", "absent", "LOW", "test", "S112"),
    )["evidence_present"] is False
    assert len(DRIFT_PROBES) == 4


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_config_drift_audit()

    assert "drift_audit=pass" in runner.summary_line(passing)
    assert "drift=4" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_config_drift_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "high_risk=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_catalog_config_drift_audit", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "drift_audit=fail" in capsys.readouterr().out
