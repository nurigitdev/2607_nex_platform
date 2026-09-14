from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0721@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0721@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "mock_first_only",
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_PROFILE": "mock-default",
        "NEX_AG_DISPATCH_LIVE_PROVIDER_MODE": "mock-http",
        "NEX_AG_DISPATCH_LIVE_PROVIDER_PROFILE": "office-webhook-profile",
        "NEX_AG_DISPATCH_HTTP_TIMEOUT_SECONDS": "15",
        "NEX_AG_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS": "5",
        "NEX_AG_DISPATCH_HTTP_READ_TIMEOUT_SECONDS": "15",
        "NEX_AG_DISPATCH_HTTP_MAX_RETRIES": "2",
        "NEX_AG_DISPATCH_HTTP_BACKOFF_SECONDS": "1.5",
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": (
            "https://notify.invalid/hook/secret-0721"
        ),
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "notify-token-shared-0721",
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": "https://incident.invalid/api",
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": "incident-token-shared-0721",
        "NEX_SERVICE_TOKEN": "service-token-shared-0721",
    }


def test_ag_dispatch_live_provider_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
        {}
    )
    boundary = evidence["live_provider_boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0721"
    assert evidence["surface"] == audit.S73_SURFACE
    assert boundary["boundary"] == audit.LIVE_PROVIDER_BOUNDARY
    assert boundary["create_table_in_slice_0721"] is False
    assert boundary["first_provider_config_slice"] == "Slice_0722"
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["planned_owned_tables"] == []
    assert boundary["live_network_calls_in_slice_0721"] is False
    assert boundary["live_network_calls_before_protected_smoke"] is False
    assert boundary["provider_execution_mode_in_0721"] == (
        "mock_first_boundary_only"
    )
    assert boundary["prepared_channel_types"] == [
        "NOTIFICATION",
        "EMAIL",
        "WEBHOOK",
        "INCIDENT",
    ]
    assert boundary["existing_mock_channel_type"] == "MOCK"
    assert boundary["result_storage"] == "safe_hashes_statuses_counters_only"
    assert boundary["raw_provider_payload_storage_allowed"] is False
    assert boundary["webhook_url_in_evidence_allowed"] is False
    assert boundary["provider_token_in_evidence_allowed"] is False
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s72_worker_and_result_contracts": True,
        "keep_provider_config_separate_from_worker_state_machine": True,
        "start_with_mock_http_transports_before_live_network": True,
        "require_explicit_opt_in_for_live_provider_smoke": True,
        "route_all_state_changes_through_dispatch_action_state_machine": True,
        "persist_only_safe_provider_hashes_statuses_and_previews": True,
        "keep_raw_provider_payloads_out_of_db_logs_and_evidence": True,
        "require_timeout_retry_and_idempotency_controls": True,
        "keep_live_notification_delivery_deferred_in_0721": True,
        "keep_live_external_incident_sync_deferred_in_0721": True,
        "avoid_new_tables_until_provider_result_needs_are_proven": True,
        "keep_table_names_short": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0722",
        "Slice_0723",
        "Slice_0724",
        "Slice_0725",
        "Slice_0726",
        "Slice_0727",
        "Slice_0728",
        "Slice_0729",
        "Slice_0730",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_escalation_dispatch_live_provider_boundary_audit=pass" in (
        summary
    )
    assert f"boundary={audit.LIVE_PROVIDER_BOUNDARY}" in summary
    assert "dispatch_table=ag_op_esc_dispatches" in summary
    assert "provider=live_readiness_only" in summary
    assert "network=deferred" in summary
    assert "next=Slice_0722" in summary


def test_ag_dispatch_live_provider_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
        env
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0721" not in serialized
    assert "notify-token-shared-0721" not in serialized
    assert "incident-token-shared-0721" not in serialized
    assert "service-token-shared-0721" not in serialized
    assert env["NEX_AG_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        key: True for key in audit.PROTECTED_ENV_KEYS
    }
    with pytest.raises(ValueError, match="NEX_AG_NOTIFICATION_SERVICE_TOKEN"):
        audit.assert_evidence_redacted("notify-token-shared-0721", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "raw_provider_payload={'secret':'do-not-emit'}",
            {},
        )
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "callback=https://notify.invalid/hook/super-secret",
            {},
        )


def test_ag_dispatch_live_provider_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_live_provider_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["s72_closed_baseline_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_dispatch_live_provider_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = (
        tmp_path
        / "services"
        / "nex-ag"
        / "nex_ag"
        / "operator_review_dispatch_execution.py"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "DISPATCH_EXECUTION_PROVIDER_PROFILES",
            "DISPATCH_EXECUTION_PROVIDER_BUCKETS",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["execution_runtime_baseline_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "provider_profiles"
    ]
    assert failed == [
        {
            "group": "execution_runtime_baseline",
            "token_id": "provider_profiles",
            "path": "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
            "purpose": "Live-provider profiles should extend the existing provider registry.",
            "present": False,
        }
    ]


def test_ag_dispatch_live_provider_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        (
            "ag_operator_review_escalation_dispatch_live_provider_http_results",
        ),
    )

    evidence = audit.run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
        {}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {item["category"] for item in evidence["issues"]} >= {
        "table_name_too_long"
    }


def test_ag_dispatch_live_provider_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
        {}
    )

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    assert audit._present_count([{"present": True}, {"present": False}, {}]) == 1
    assert audit._present_count(None) == 0
    assert audit._grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"blocked": False, "ready": True}
    assert audit._read_text(ROOT / "docs" / "README.md")
    assert audit._read_text(tmp_path / "missing.md") == ""

    pass_evidence = {
        "status": "PASS",
        "live_provider_boundary": {"boundary": audit.LIVE_PROVIDER_BOUNDARY},
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert "ag_operator_review_escalation_dispatch_live_provider_boundary_audit=pass" in (
        capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": (
            "ag_operator_review_escalation_dispatch_live_provider_boundary_failed"
        ),
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ag_dispatch_live_provider_boundary_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
            "--summary",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(
                ROOT
                / "scripts"
                / "smoke"
                / "run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py"
            ),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "ag_operator_review_escalation_dispatch_live_provider_boundary_audit=pass" in (
        capsys.readouterr().out
    )


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
