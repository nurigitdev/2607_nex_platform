from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_recovery_notification_delivery_boundary_audit as audit


def test_recovery_notification_delivery_boundary_passes_repo() -> None:
    evidence = audit.run_ag_recovery_notification_delivery_boundary_audit()

    assert evidence["status"] == "PASS"
    assert evidence["requirement"] == "S85"
    assert evidence["decision"]["status"] == "REQUIRED_BEFORE_IMPLEMENTATION"
    assert evidence["decision"]["recommended_option"] == audit.RECOMMENDED_OPTION
    assert evidence["decision"]["safe_to_implement_next_slice"] is False
    assert evidence["boundary"]["mandatory_existing_context"] == [
        "case_id",
        "escalation_id",
    ]
    assert evidence["boundary"]["new_table_in_slice_0841"] is False
    assert evidence["boundary"]["provider_invocation_in_slice_0841"] is False
    assert evidence["issues"] == []
    assert all(evidence["checks"].values())
    assert "boundary=pass" in audit.summary_line(evidence)


def test_recovery_notification_delivery_boundary_reports_missing_repo(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_recovery_notification_delivery_boundary_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }


def test_recovery_notification_delivery_boundary_reports_missing_tokens(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_recovery_notification_delivery_boundary_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["existing_outbox_is_reusable"] is False
    assert evidence["checks"]["existing_outbox_requires_case_and_escalation"] is False
    assert evidence["checks"]["s84_delivery_guardrails_remain_closed"] is False


def test_recovery_notification_delivery_boundary_identifier_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "EXISTING_DISPATCH_TABLE",
        "ag_recovery_notification_dispatch_outbox_too_long",
    )

    evidence = audit.run_ag_recovery_notification_delivery_boundary_audit()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["identifier_lengths_safe"] is False
    assert any(
        item["category"] == "identifier_too_long" for item in evidence["issues"]
    )


def test_recovery_notification_delivery_boundary_helpers(tmp_path: Path) -> None:
    assert audit._read_text(tmp_path / "missing.md") == ""
    assert audit._group_present([], "missing") is False
    assert audit.summary_line({}) == (
        "ag_recovery_notification_delivery_boundary=fail decision=None "
        "recommended=None safe_next=None"
    )


def test_recovery_notification_delivery_boundary_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_recovery_notification_delivery_boundary_audit",
        lambda: {
            "status": "PASS",
            "decision": {
                "status": "REQUIRED_BEFORE_IMPLEMENTATION",
                "recommended_option": audit.RECOMMENDED_OPTION,
                "safe_to_implement_next_slice": False,
            },
        },
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_recovery_notification_delivery_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main(["--summary"]) == 1
    assert "boundary=fail" in capsys.readouterr().out
