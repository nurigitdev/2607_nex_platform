from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence as evidence


def test_expiry_privacy_runbook_evidence_passes() -> None:
    result = evidence.run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["surface_count"] == 10
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["applied"]["applied_count"] == 1
    assert result["surfaces"]["idempotent_rerun"]["candidate_count"] == 0
    assert result["surfaces"]["conflict"]["outcome_statuses"] == ["CONFLICT"]
    assert result["surfaces"]["invalid_request"]["status_code"] == 400
    assert result["surfaces"]["store_unavailable"]["status_code"] == 503
    assert all(result["checks"].values())
    assert "privacy_runbook=pass" in evidence.summary_line(result)


def test_expiry_privacy_runbook_reports_route_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "_route_evidence",
        lambda _root: {"static_ready": True, "runtime_ready": False},
    )

    result = evidence.run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence()

    assert result["status"] == "FAIL"
    assert result["checks"]["runtime_route_ready"] is False
    assert "privacy_runbook=fail" in evidence.summary_line(result)


def test_expiry_privacy_runbook_reports_migration_and_doc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "_migration_evidence",
        lambda _root: {
            "ready": False,
            "identifier_lengths_safe": False,
        },
    )
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if str(path).endswith("0818_ag_dispatch_liveness_ack_expiry_postgres_smoke.md"):
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    result = evidence.run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence()

    assert result["status"] == "FAIL"
    assert result["checks"]["migration_ready"] is False
    assert result["checks"]["identifier_lengths_safe"] is False
    assert result["checks"]["docs_present"] is False


def test_expiry_privacy_runbook_detects_forbidden_values_and_keys() -> None:
    payload = {
        "safe": [
            {
                "raw_comment": evidence.FORBIDDEN_VALUES["raw_comment"],
            }
        ]
    }
    serialized = str(payload)

    assert evidence._forbidden_key_paths(payload) == ["safe[0].raw_comment"]
    assert evidence._forbidden_value_labels(serialized) == ["raw_comment"]
    with pytest.raises(ValueError):
        evidence._assert_no_forbidden_values(serialized)


def test_expiry_privacy_runbook_helper_defaults() -> None:
    assert evidence._forbidden_key_paths("safe") == []
    assert evidence._response_surface(
        type("Response", (), {"status_code": 200, "json": lambda self: {}})()
    ) == {
        "status_code": 200,
        "run_status": None,
        "candidate_count": None,
        "applied_count": None,
        "conflict_count": None,
        "error_code": None,
        "outcome_statuses": [],
    }
    actions = evidence._runbook_actions()
    assert actions["503"]["retryable"] is False
    assert actions["idempotent_rerun"]["retryable"] is False


def test_expiry_privacy_runbook_main_and_quality_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence",
        lambda: {"status": "PASS", "surface_count": 1, "checks": {}},
    )
    assert evidence.main(["--summary"]) == 0
    assert "privacy_runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert evidence.main(["--summary"]) == 1
    assert "privacy_runbook=fail" in capsys.readouterr().out

    quality_gate = (
        evidence.ROOT / "scripts" / "quality" / "run_quality_gate.sh"
    ).read_text(encoding="utf-8")
    assert evidence.EVIDENCE_HOOK in quality_gate
