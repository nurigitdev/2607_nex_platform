from __future__ import annotations

from pathlib import Path

from nex_mo.precision_resource_audit import (
    EVIDENCE_PROBES,
    EvidenceProbe,
    _inspect_probe,
    build_mo_precision_resource_safety_audit,
)
import run_mo_precision_resource_safety_audit as runner


def test_repository_precision_and_resource_safety_is_classified() -> None:
    result = build_mo_precision_resource_safety_audit()

    assert result["status"] == "PASS"
    assert result["precision_readiness"] == "DECLARED_SAFE_RUNTIME_EVIDENCE_REQUIRED"
    assert result["resource_metrics_readiness"] == "GAP_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "selected_profile_count": 3,
        "bf16_selected_count": 3,
        "evidence_probe_count": 5,
        "evidence_issue_count": 0,
        "runtime_gap_count": 2,
    }
    assert result["precision_by_capability"] == {
        "embedding": "BF16",
        "reranking": "BF16",
        "generation": "BF16",
    }
    assert result["runtime_gaps"][0]["verification_slice"] == "1110"


def test_audit_fails_closed_for_missing_evidence(tmp_path: Path) -> None:
    probes = (EvidenceProbe("missing", "missing.py", "token"),)

    result = build_mo_precision_resource_safety_audit(tmp_path, probes=probes)

    assert result["status"] == "FAIL"
    assert result["precision_readiness"] == "BLOCKED"
    assert result["resource_metrics_readiness"] == "BLOCKED"
    assert result["checks"]["precision_evidence_present"] is False
    assert result["checks"]["mo_has_no_local_model_loader"] is True
    assert result["issues"] == [
        {
            "category": "precision_evidence_missing",
            "probe_id": "missing",
            "path": "missing.py",
        }
    ]


def test_probe_inspection_covers_present_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "probe.py"
    path.write_text("expected token\n", encoding="utf-8")

    assert _inspect_probe(
        tmp_path, EvidenceProbe("present", "probe.py", "expected")
    )["present"] is True
    assert _inspect_probe(
        tmp_path, EvidenceProbe("missing", "probe.py", "absent")
    )["present"] is False
    assert len(EVIDENCE_PROBES) == 5


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_precision_resource_safety_audit()

    assert "safety_audit=pass" in runner.summary_line(passing)
    assert "bf16=3/3" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_mo_precision_resource_safety_audit",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "runtime_gaps=2" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(
        runner,
        "run_mo_precision_resource_safety_audit",
        lambda: failing,
    )
    assert runner.main(["--summary"]) == 1
    assert "safety_audit=fail" in capsys.readouterr().out
