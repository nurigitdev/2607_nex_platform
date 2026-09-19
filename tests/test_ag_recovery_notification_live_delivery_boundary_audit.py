from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_recovery_notification_live_delivery_boundary_audit as audit


def test_live_delivery_boundary_passes_repo() -> None:
    evidence = audit.run_ag_recovery_notification_live_delivery_boundary_audit()

    assert evidence["status"] == "PASS"
    assert evidence["requirement"] == "S86"
    assert evidence["decision"] == {
        "status": "APPROVED_BOUNDARY",
        "boundary": audit.BOUNDARY,
        "safe_to_implement_next_slice": True,
        "planner_change": "explicit_allow_live_channel_flag_default_false",
        "execution_change": "targeted_live_http_worker_adapter",
        "external_endpoint_strategy": "local_loopback_until_full_system",
    }
    assert evidence["boundary"]["existing_dispatch_table"] == (
        "ag_op_esc_dispatches"
    )
    assert evidence["boundary"]["eligible_live_channels"] == [
        "NOTIFICATION",
        "EMAIL",
        "WEBHOOK",
    ]
    assert evidence["boundary"]["incident_channel_in_s86"] is False
    assert evidence["boundary"]["new_table_in_slice_0851"] is False
    assert evidence["boundary"]["provider_invocation_in_slice_0851"] is False
    assert evidence["issues"] == []
    assert all(evidence["checks"].values())


def test_live_delivery_boundary_summary() -> None:
    summary = audit.summary_line(
        audit.run_ag_recovery_notification_live_delivery_boundary_audit()
    )

    assert "live_delivery_boundary=pass" in summary
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "network=disabled" in summary
    assert "smoke=local_loopback_http_server" in summary
    assert "safe_next=True" in summary


def test_live_delivery_boundary_reports_missing_repo(tmp_path: Path) -> None:
    evidence = audit.run_ag_recovery_notification_live_delivery_boundary_audit(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["decision"]["safe_to_implement_next_slice"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }


def test_live_delivery_boundary_reports_missing_tokens(tmp_path: Path) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_recovery_notification_live_delivery_boundary_audit(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["s85_closed"] is False
    assert evidence["checks"]["current_live_guard_identified"] is False
    assert evidence["checks"]["existing_live_runtime_reusable"] is False
    assert all(
        item["category"] == "source_token_missing"
        for item in evidence["issues"]
    )


def test_live_delivery_boundary_identifier_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "EXISTING_DISPATCH_TABLE",
        "ag_recovery_notification_live_delivery_dispatches_too_long",
    )

    evidence = audit.run_ag_recovery_notification_live_delivery_boundary_audit()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["identifier_lengths_safe"] is False
    assert any(
        item["category"] == "identifier_too_long"
        for item in evidence["issues"]
    )


def test_live_delivery_boundary_helpers(tmp_path: Path) -> None:
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit._group_present([], "missing") is False
    assert audit.summary_line({}) == (
        "ag_recovery_notification_live_delivery_boundary=fail boundary=None "
        "network=disabled smoke=None safe_next=None"
    )


def test_live_delivery_boundary_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert audit.main(["--summary"]) == 0
    assert "live_delivery_boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_recovery_notification_live_delivery_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main(["--summary"]) == 1
    assert "live_delivery_boundary=fail" in capsys.readouterr().out
