from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_recovery_notification_policy_boundary_audit as audit


def test_recovery_notification_policy_boundary_passes_repo() -> None:
    evidence = audit.run_ag_recovery_notification_policy_boundary_audit()

    assert evidence["status"] == "PASS"
    assert evidence["requirement"] == "S84"
    assert evidence["boundary"]["owner_service"] == "nex-ag"
    assert evidence["boundary"]["new_table_in_slice_0831"] is False
    assert evidence["boundary"]["outbound_provider_call_in_s84"] is False
    assert evidence["decisions"]["delivery_is_disabled_by_default"] is True
    assert evidence["decisions"]["active_suppression_is_policy_input"] is True
    assert evidence["issues"] == []
    assert all(evidence["checks"].values())
    assert "boundary=pass" in audit.summary_line(evidence)


def test_recovery_notification_policy_boundary_reports_missing_repo(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_recovery_notification_policy_boundary_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }


def test_recovery_notification_policy_boundary_reports_missing_token(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_recovery_notification_policy_boundary_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["s83_closed"] is False


def test_recovery_notification_policy_boundary_identifier_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "EVENT_TABLE", "event_table_name_exceeding_policy_limit")

    evidence = audit.run_ag_recovery_notification_policy_boundary_audit()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["identifier_lengths_safe"] is False
    assert any(
        item["category"] == "identifier_too_long" for item in evidence["issues"]
    )


def test_recovery_notification_policy_boundary_helpers(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    assert audit._read_text(missing) == ""
    assert audit._group_present([], "missing") is False
    assert audit.summary_line({}) == (
        "ag_recovery_notification_policy_boundary=fail owner=None "
        "provider_call=None new_table=None next=None"
    )


def test_recovery_notification_policy_boundary_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_recovery_notification_policy_boundary_audit",
        lambda: {
            "status": "PASS",
            "boundary": {
                "owner_service": "nex-ag",
                "outbound_provider_call_in_s84": False,
                "new_table_in_slice_0831": False,
            },
            "slice_plan": ["Slice_0832_policy_configuration_contract"],
        },
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_recovery_notification_policy_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main(["--summary"]) == 1
    assert "boundary=fail" in capsys.readouterr().out
