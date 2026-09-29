from __future__ import annotations

from pathlib import Path

from nex_mo.resilience_readiness_audit import (
    CONTROL_PROBES,
    ControlProbe,
    _inspect_probe,
    build_mo_resilience_telemetry_readiness_audit,
)
import run_mo_resilience_telemetry_readiness_audit as runner


def test_repository_resilience_and_readiness_gaps_are_classified() -> None:
    result = build_mo_resilience_telemetry_readiness_audit()

    assert result["status"] == "PASS"
    assert result["operations_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "implemented_control_count": 5,
        "classified_control_gap_count": 2,
        "failure_decision_count": 5,
        "telemetry_capability_count": 3,
        "runtime_gap_count": 5,
        "evidence_issue_count": 0,
    }
    assert [item["risk"] for item in result["runtime_gaps"]] == [
        "HIGH",
        "MEDIUM",
        "MEDIUM",
        "MEDIUM",
        "LOW",
    ]
    assert all("detail" not in item for item in result["failure_decisions"])


def test_audit_fails_closed_for_missing_control_evidence(tmp_path: Path) -> None:
    probes = (ControlProbe("missing", "missing.py", "token", "IMPLEMENTED"),)

    result = build_mo_resilience_telemetry_readiness_audit(tmp_path, probes=probes)

    assert result["status"] == "FAIL"
    assert result["operations_readiness"] == "BLOCKED"
    assert result["checks"]["control_inventory_complete"] is False
    assert result["checks"]["control_evidence_present"] is False
    assert result["issues"] == [
        {
            "category": "resilience_evidence_missing",
            "control_id": "missing",
            "path": "missing.py",
        }
    ]


def test_probe_inspection_covers_present_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "probe.py"
    path.write_text("expected token\n", encoding="utf-8")

    assert _inspect_probe(
        tmp_path,
        ControlProbe("present", "probe.py", "expected", "IMPLEMENTED"),
    )["evidence_present"] is True
    assert _inspect_probe(
        tmp_path,
        ControlProbe("missing", "probe.py", "absent", "GAP"),
    )["evidence_present"] is False
    assert len(CONTROL_PROBES) == 7


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_resilience_telemetry_readiness_audit()

    assert "readiness_audit=pass" in runner.summary_line(passing)
    assert "runtime_gaps=5" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_mo_resilience_telemetry_readiness_audit",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "telemetry=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(
        runner,
        "run_mo_resilience_telemetry_readiness_audit",
        lambda: failing,
    )
    assert runner.main(["--summary"]) == 1
    assert "readiness_audit=fail" in capsys.readouterr().out
