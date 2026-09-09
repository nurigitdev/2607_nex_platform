from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ae_operator_control_execution_worker_result_persistence_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0611@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0611@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE": "1",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE": "1",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE": "1",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0611",
        "NEX_SERVICE_TOKEN": "service-token-shared-0611",
    }


def test_ae_operator_control_execution_worker_result_persistence_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
            {}
        )
    )

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0611"
    assert evidence["surface"] == audit.S62_SURFACE
    assert evidence["result_persistence_boundary"] == {
        "system_of_record": "nex-ae-api",
        "persistence_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "boundary": "ae_owned_safe_summary_worker_result_persistence",
        "create_table_in_slice_0611": False,
        "first_schema_slice": "Slice_0612",
        "candidate_result_table": "ae_op_exec_worker_results",
        "candidate_result_table_length": 25,
        "candidate_event_table": "ae_op_exec_worker_events",
        "candidate_event_table_length": 24,
        "event_table_deferred": True,
        "max_table_name_length": 30,
        "storage_shape": "safe_summary_plus_hashes",
        "persist_flag": "persist_worker_result",
        "default_persist_worker_result": False,
        "explicit_opt_in_required": True,
        "test_profile_smoke_required": True,
        "postgres_smoke_required_before_ag_enablement": True,
        "store_columns": [
            "operator_control_execution_worker_result_id",
            "operator_control_execution_state_id",
            "operator_control_execution_request_id",
            "operator_control_execution_worker_command_id",
            "operator_control_execution_worker_plan_id",
            "operator_control_execution_worker_transition_plan_id",
            "scheduler_id",
            "action",
            "execution_mode",
            "worker_mode",
            "worker_status",
            "decision_reason",
            "observed_at",
            "supervisor_result_count",
            "created_at",
            "updated_at",
        ],
        "store_jsonb_columns": [
            "status_path",
            "supervisor_result_statuses",
            "supervisor_actions",
            "supervisor_result_ids",
            "guardrails",
            "metadata",
        ],
        "store_hash_columns": [
            "operator_control_execution_worker_command_hash",
            "operator_control_execution_worker_transition_plan_hash",
        ],
        "forbidden_persistence_payloads": [
            "full_worker_command_payload",
            "full_transition_plan_payload",
            "full_supervisor_result_payload",
            "database_url",
            "service_token",
            "provider_api_key",
            "local_storage_path",
            "artifact_payload",
            "execution_payload",
            "daemon_runtime_payload",
            "supervised_process_snapshot",
        ],
        "recommended_indexes": [
            "worker_result_id_unique",
            "execution_state_id",
            "worker_status_observed_at",
            "scheduler_action_observed_at",
        ],
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "worker_result_blob_storage_allowed": False,
        "physical_delete_automation_enabled": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "separate_persistence_projection_from_full_worker_result_contract": True,
        "keep_worker_result_builder_validation_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "add_repository_before_route_write_toggle": True,
        "make_persist_worker_result_explicit": True,
        "default_route_remains_non_persistent": True,
        "reuse_existing_execution_state_identity": True,
        "reuse_existing_transition_evidence_without_replacing_it": True,
        "store_safe_summary_and_hashes_only": True,
        "do_not_store_full_worker_command_payload": True,
        "do_not_store_full_transition_plan_payload": True,
        "do_not_store_full_supervisor_result_payload": True,
        "keep_ag_read_only": True,
        "require_real_test_db_smoke_before_ag_result_routes": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0612",
        "Slice_0613",
        "Slice_0614",
        "Slice_0615",
        "Slice_0616",
        "Slice_0617",
        "Slice_0618",
        "Slice_0619",
        "Slice_0620",
    ]
    summary = audit.summary_line(evidence)
    assert (
        "ae_operator_control_execution_worker_result_persistence_boundary_audit=pass"
        in summary
    )
    assert "result_table=ae_op_exec_worker_results" in summary
    assert "next=Slice_0612" in summary


def test_ae_operator_control_execution_worker_result_persistence_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = (
        audit.run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
            env
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0611" not in serialized
    assert "service-token-0611" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE": True,
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE": True,
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ae_operator_control_execution_worker_result_persistence_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
            {},
            root_dir=tmp_path,
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ae_operator_control_execution_worker_result_persistence_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["quality_docs_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_operator_control_execution_worker_result_persistence_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = (
        tmp_path
        / "services"
        / "nex-ae-api"
        / "nex_ae_api"
        / "artifact_retention_scheduler_daemon.py"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            '"operator_control_execution_worker_command_hash"',
            '"operator_control_execution_worker_command_digest"',
        ),
        encoding="utf-8",
    )

    evidence = (
        audit.run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
            {},
            root_dir=tmp_path,
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ae_worker_safe_summary_source_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "worker_command_hash"
    ]
    assert failed == [
        {
            "group": "ae_worker_safe_summary_source",
            "token_id": "worker_command_hash",
            "path": (
                "services/nex-ae-api/nex_ae_api/"
                "artifact_retention_scheduler_daemon.py"
            ),
            "purpose": (
                "Persist hashes for raw command correlation instead of raw "
                "command payloads."
            ),
            "present": False,
        }
    ]


def test_ae_operator_control_execution_worker_result_persistence_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ae_operator_control_execution_worker_result_rows",
                "length": 48,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = (
        audit.run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
            {}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {
        item["category"] for item in evidence["issues"]
    } >= {"table_name_too_long"}


def test_ae_operator_control_execution_worker_result_persistence_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = (
        audit.run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
            {}
        )
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
    assert audit._table_name_results() == [
        {
            "table_name": "ae_op_exec_worker_results",
            "length": 25,
            "max_length": 30,
            "within_limit": True,
        },
        {
            "table_name": "ae_op_exec_worker_events",
            "length": 24,
            "max_length": 30,
            "within_limit": True,
        },
    ]

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit._assert_evidence_redacted(
            protected_env()["NEX_AE_TEST_DATABASE_URL"],
            protected_env(),
        )
    for leaked in (
        "db=postgresql://user:pass@host/db",
        "Authorization: Bearer token",
        "provider=ed6@c496em",
        "password=nuri1004",
        "/data/nex-platform/private",
        "idempotency_key=unsafe",
        "full_worker_command_payload={}",
        "full_transition_plan_payload={}",
        "full_supervisor_result_payload={}",
        "raw_execution_payload",
    ):
        with pytest.raises(ValueError, match="Sensitive value leaked"):
            audit._assert_evidence_redacted(leaked, {})

    monkeypatch.setattr(
        audit,
        "run_ae_operator_control_execution_worker_result_persistence_boundary_audit",
        lambda: evidence,
    )
    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert (
        "ae_operator_control_execution_worker_result_persistence_boundary_audit=pass"
        in capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ae_operator_control_execution_worker_result_persistence_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "test",
            "checks": {"required_paths_present": False},
        },
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
