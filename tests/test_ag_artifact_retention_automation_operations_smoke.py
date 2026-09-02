from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

import run_ag_artifact_retention_automation_operations_smoke as smoke
from nex_ag.artifact_operations import InMemoryAeArtifactOperationsClient


def test_ag_artifact_retention_automation_operations_smoke_passes() -> None:
    evidence = smoke.run_ag_artifact_retention_automation_operations_smoke()

    assert evidence["status"] == "PASS"
    assert evidence["response_status"] == 200
    assert evidence["summary"]["safety_status"] == "FAILED_ATTENTION"
    assert evidence["summary"]["approval_blocked_count"] == 1
    assert evidence["summary"]["daemon_manual_tick_once_available"] is True
    assert evidence["checks"]["daemon_rollup_visible"] is True
    assert all(evidence["checks"].values())


def test_ag_artifact_retention_automation_operations_smoke_detects_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_smoke_source_client",
        lambda: InMemoryAeArtifactOperationsClient(),
    )

    evidence = smoke.run_ag_artifact_retention_automation_operations_smoke()

    assert evidence["status"] == "FAIL"
    assert evidence["response_status"] == 200
    assert evidence["checks"]["schema_version"] is True
    assert evidence["checks"]["dispatch_available"] is False
    assert evidence["checks"]["operator_attention"] is False
    assert "failing_checks" in smoke.summary_line(evidence)


def test_ag_artifact_retention_automation_operations_smoke_redaction_guard() -> None:
    with pytest.raises(ValueError, match="private data"):
        smoke.assert_smoke_evidence_redacted({"summary": {"database_url": "secret"}})

    assert smoke._is_redacted({"safe": True}) is True
    assert smoke._is_redacted({"unsafe": "/data/nex-platform/ae/private.md"}) is False
    assert smoke._smoke_checks(500, []) == {
        "route_status_ok": False,
        "schema_version": False,
        "dispatch_available": False,
        "operator_attention": False,
        "approval_gate_visible": False,
        "daemon_rollup_visible": False,
        "no_direct_ag_mutation": False,
        "metadata_only": False,
        "redacted": False,
    }
    malformed = smoke._smoke_checks(
        200,
        {
            "projection_schema_version": (
                smoke.AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
            ),
            "summary": "bad",
            "operator_guidance": "bad",
        },
    )
    assert malformed["schema_version"] is True
    assert malformed["dispatch_available"] is False
    assert malformed["daemon_rollup_visible"] is False
    assert malformed["no_direct_ag_mutation"] is False
    assert "safety=None" in smoke.summary_line(
        {"status": "FAIL", "response_status": 500, "summary": "bad", "checks": {}}
    )


def test_ag_artifact_retention_automation_operations_smoke_cli_and_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "ag-automation-smoke.json"

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "ag_artifact_retention_automation_operations_smoke=pass" in (
        capsys.readouterr().out
    )
    assert "FAILED_ATTENTION" in output_path.read_text(encoding="utf-8")
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_artifact_retention_automation_operations_smoke",
        lambda: {"status": "FAIL", "response_status": 200, "summary": {}, "checks": {}},
    )
    assert smoke.main(["--summary"]) == 1
    assert "ag_artifact_retention_automation_operations_smoke=fail" in (
        capsys.readouterr().out
    )

    def broken_runner() -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        smoke, "run_ag_artifact_retention_automation_operations_smoke", broken_runner
    )
    monkeypatch.setattr(
        sys, "argv", ["run_ag_artifact_retention_automation_operations_smoke.py"]
    )
    assert smoke.main() == 1
    assert "ag_artifact_retention_automation_operations_smoke=fail" in (
        capsys.readouterr().out
    )
