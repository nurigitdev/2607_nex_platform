from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit as audit


def test_ag_dispatch_live_http_transport_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit()
    )
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0731"
    assert evidence["surface"] == audit.S74_SURFACE
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["create_table_in_slice_0731"] is False
    assert boundary["live_network_calls_in_slice_0731"] is False
    assert boundary["real_external_endpoint_available"] is False
    assert boundary["protected_smoke_strategy"] == "local_loopback_http_server"
    assert boundary["real_endpoint_smoke_deferred_until_full_system"] is True
    assert boundary["first_transport_slice"] == "Slice_0732"
    assert boundary["first_loopback_notification_smoke_slice"] == "Slice_0735"
    assert boundary["first_loopback_incident_smoke_slice"] == "Slice_0736"
    assert boundary["provider_modes_allowed_now"] == [
        "mock_first_only",
        "mock_http",
    ]
    assert boundary["raw_provider_payload_storage_allowed"] is False
    assert boundary["authorization_header_in_evidence_allowed"] is False
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s73_provider_config_and_request_contracts": True,
        "keep_transport_injected_not_global": True,
        "start_with_local_loopback_http_server": True,
        "defer_real_external_endpoint_until_full_system": True,
        "require_live_enable_env_for_network": True,
        "preserve_mock_first_default": True,
        "route_state_changes_through_dispatch_action_state_machine": True,
        "persist_only_safe_hashes_statuses_and_diagnostics": True,
        "keep_authorization_headers_out_of_logs_and_evidence": True,
        "keep_raw_provider_payloads_out_of_db_logs_and_evidence": True,
        "keep_table_names_short": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0732",
        "Slice_0733",
        "Slice_0734",
        "Slice_0735",
        "Slice_0736",
        "Slice_0737",
        "Slice_0738",
        "Slice_0739",
        "Slice_0740",
    ]


def test_ag_dispatch_live_http_transport_boundary_summary() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit()
    )
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_live_http_transport_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "network=disabled" in summary
    assert "smoke=local_loopback_http_server" in summary
    assert "real_endpoint_deferred=True" in summary
    assert "next=Slice_0732" in summary


def test_ag_dispatch_live_http_transport_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_live_http_transport_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "live_http_transport_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_live_http_transport_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)
    for item in audit.REQUIRED_PATHS:
        path = root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit(
        root
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["runtime_baseline_present"] is False
    assert all(item["category"] == "source_token_missing" for item in evidence["issues"])


def test_ag_dispatch_live_http_transport_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        ("ag_operator_review_escalation_dispatch_live_http_transport_results",),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert evidence["issues"] == [
        {
            "category": "table_name_too_long",
            "table": "ag_operator_review_escalation_dispatch_live_http_transport_results",
            "length": 66,
            "limit": audit.MAX_TABLE_NAME_LENGTH,
        }
    ]


def test_ag_dispatch_live_http_transport_boundary_main(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert audit.main(["--summary"]) == 0
    assert "live_http_transport_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root
