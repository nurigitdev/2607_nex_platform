from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ADAPTER_NAME,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_MODE,
    FakeArtifactRetentionSchedulerDaemonSupervisorAdapter,
    build_artifact_retention_scheduler_daemon_supervisor_command,
    build_artifact_retention_scheduler_daemon_supervisor_result,
    run_artifact_retention_scheduler_daemon_supervisor_command,
    summarize_artifact_retention_scheduler_daemon_supervisor_command,
    summarize_artifact_retention_scheduler_daemon_supervisor_result,
    supervisor_command_summary_line,
    supervisor_result_summary_line,
    validate_artifact_retention_scheduler_daemon_supervisor_command,
    validate_artifact_retention_scheduler_daemon_supervisor_result,
)
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    build_artifact_retention_scheduler_config,
)
from nex_runtime import InMemoryJobQueue


CHECKED_AT = "2026-09-01T01:00:00Z"
OBSERVED_AT = "2026-09-01T01:00:03Z"


def test_supervisor_status_probe_command_is_metadata_only() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        checked_at=CHECKED_AT,
        requested_by={"actor_type": "operator", "actor_id": "ag-admin"},
        reason="operator_status_check",
    )
    summary = summarize_artifact_retention_scheduler_daemon_supervisor_command(
        command
    )
    serialized = json.dumps(command, ensure_ascii=False, sort_keys=True)

    assert command["daemon_supervisor_command_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION
    )
    assert command["service_id"] == "nex-ae-api"
    assert command["command"] == {
        "action": "status_probe",
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "profile": "test",
        "enabled": False,
        "explicit_opt_in": False,
        "checked_at": CHECKED_AT,
        "max_cycles": 1,
        "run_worker": False,
        "output_format": "json",
        "supervisor_mode": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_MODE,
    }
    assert command["runtime_state"]["lifecycle_status"] == "DISABLED"
    assert command["execution_plan"] == {
        "loads_runtime_config": True,
        "validates_daemon_config": True,
        "builds_runtime_state": True,
        "reads_status": True,
        "requests_start": False,
        "requests_stop": False,
        "runtime_ready": False,
        "supervisor_adapter_required": False,
        "supervisor_adapter_available": False,
        "supervisor_adapter_invoked": False,
        "starts_process": False,
        "stops_process": False,
        "delegates_cli_execution": False,
        "bounded_loop_is_finite": True,
        "writes_database": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }
    assert command["guardrails"]["metadata_only"] is True
    assert command["guardrails"]["supervisor_owner_ae"] is True
    assert command["guardrails"]["ag_direct_process_control_allowed"] is False
    assert command["metadata"]["safe_for_ag_projection"] is True
    assert command["metadata"]["requested_by"] == {
        "actor_type": "operator",
        "actor_id": "ag-admin",
    }
    assert summary["action"] == "status_probe"
    assert summary["runtime_ready"] is False
    assert summary["starts_process"] is False
    assert validate_artifact_retention_scheduler_daemon_supervisor_command(
        command
    ) == command
    assert "ae_scheduler_daemon_supervisor_command=pass" in (
        supervisor_command_summary_line(command)
    )
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_supervisor_start_command_requires_test_profile_opt_in_and_stays_unstarted() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="start_daemon",
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        max_cycles="3",
        run_worker=True,
        output_format="summary",
    )
    result = build_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_command=command,
        observed_at=OBSERVED_AT,
    )
    command_summary = summarize_artifact_retention_scheduler_daemon_supervisor_command(
        command
    )
    result_summary = summarize_artifact_retention_scheduler_daemon_supervisor_result(
        result
    )

    assert command["command"]["action"] == "start_daemon"
    assert command["command"]["max_cycles"] == 3
    assert command["command"]["run_worker"] is True
    assert command["runtime_config"]["enablement"]["enablement_status"] == "READY"
    assert command["runtime_state"]["lifecycle_status"] == "STARTING"
    assert command["execution_plan"]["runtime_ready"] is True
    assert command["execution_plan"]["supervisor_adapter_required"] is True
    assert command["execution_plan"]["supervisor_adapter_invoked"] is False
    assert command["execution_plan"]["starts_process"] is False
    assert command["guardrails"]["execution_requires_explicit_opt_in"] is True
    assert command["metadata"]["bounded_loop_requested"] is True
    assert command_summary["safe_for_ag_projection"] is True
    assert result["daemon_supervisor_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION
    )
    assert result["result_status"] == "BLOCKED"
    assert result["decision_reason"] == "supervisor_adapter_not_configured"
    assert result["execution_plan"]["start_blocked_by_missing_supervisor_adapter"] is True
    assert result["execution_plan"]["starts_process"] is False
    assert result["guardrails"]["process_started"] is False
    assert result["metadata"]["bounded_loop_started"] is False
    assert result_summary["process_started"] is False
    assert validate_artifact_retention_scheduler_daemon_supervisor_result(
        result
    ) == result
    assert "status=BLOCKED" in supervisor_result_summary_line(result)


def test_supervisor_stop_command_defaults_to_noop_without_process() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="STOP_DAEMON",
        checked_at=CHECKED_AT,
    )
    result = build_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_command=command,
        observed_at=OBSERVED_AT,
        message="no daemon process registered",
    )

    assert command["command"]["action"] == "stop_daemon"
    assert command["runtime_state"]["lifecycle_status"] == "DISABLED"
    assert command["guardrails"]["stop_daemon_requires_supervisor_adapter"] is True
    assert result["result_status"] == "NOOP"
    assert result["decision_reason"] == "daemon_not_running"
    assert result["message"] == "no daemon process registered"
    assert result["execution_plan"]["stop_noop_without_running_process"] is True
    assert "process_stopped=0" in supervisor_result_summary_line(result)


def test_supervisor_start_rejects_disabled_or_untrusted_enablement() -> None:
    with pytest.raises(ArtifactHandoffError) as disabled_exc:
        build_artifact_retention_scheduler_daemon_supervisor_command(
            action="start_daemon",
            checked_at=CHECKED_AT,
        )
    assert disabled_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid"
    )
    assert "explicit opt-in" in disabled_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as profile_exc:
        build_artifact_retention_scheduler_daemon_supervisor_command(
            action="status_probe",
            profile="dev",
            checked_at=CHECKED_AT,
        )
    assert profile_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid"
    )
    assert "profile is invalid" in profile_exc.value.detail


def test_supervisor_command_validation_edges() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="start_daemon",
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        max_cycles=2,
    )
    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "object",
        ),
        (
            {**command, "daemon_supervisor_command_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_schema_invalid",
            "schema",
        ),
        (
            {**command, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "service id",
        ),
        (
            {**command, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "scope",
        ),
        (
            {**command, "command": "bad"},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "command",
        ),
        (
            {**command, "command": {**command["command"], "unexpected": True}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "command keys",
        ),
        (
            {
                **command,
                "command": {
                    **command["command"],
                    "entrypoint": "python daemon.py",
                },
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "entrypoint",
        ),
        (
            {**command, "command": {**command["command"], "action": "launch"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "action",
        ),
        (
            {**command, "command": {**command["command"], "profile": "dev"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "profile",
        ),
        (
            {**command, "command": {**command["command"], "enabled": False}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "enabled flag",
        ),
        (
            {**command, "command": {**command["command"], "explicit_opt_in": False}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "explicit opt-in",
        ),
        (
            {**command, "command": {**command["command"], "checked_at": "later"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "checked_at",
        ),
        (
            {**command, "command": {**command["command"], "max_cycles": 0}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "positive integer",
        ),
        (
            {**command, "command": {**command["command"], "run_worker": "yes"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "run_worker",
        ),
        (
            {**command, "command": {**command["command"], "output_format": "yaml"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "output format",
        ),
        (
            {**command, "command": {**command["command"], "supervisor_mode": "systemd"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "mode",
        ),
        (
            {
                **command,
                "runtime_state": {
                    **command["runtime_state"],
                    "lifecycle_status": "DISABLED",
                },
            },
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "disabled state reason",
        ),
        (
            {
                **command,
                "execution_plan": {**command["execution_plan"], "starts_process": True},
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "execution plan",
        ),
        (
            {
                **command,
                "guardrails": {
                    **command["guardrails"],
                    "ag_direct_process_control_allowed": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "guardrails",
        ),
        (
            {
                **command,
                "metadata": {**command["metadata"], "process_started": True},
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "metadata",
        ),
        (
            {**command, "daemon_supervisor_command_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "id",
        ),
        (
            {**command, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_supervisor_command(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


def test_supervisor_result_validation_edges() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="start_daemon",
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
    )
    result = build_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_command=command,
        observed_at=OBSERVED_AT,
    )
    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "object",
        ),
        (
            {**result, "daemon_supervisor_result_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_schema_invalid",
            "schema",
        ),
        (
            {**result, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "service id",
        ),
        (
            {**result, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "command scope",
        ),
        (
            {**result, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "command scope",
        ),
        (
            {**result, "result_status": "started"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "status",
        ),
        (
            {**result, "decision_reason": "wrong"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "decision reason",
        ),
        (
            {**result, "supervisor_command": deepcopy({**command, "scheduler_id": "x"})},
            "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid",
            "scope",
        ),
        (
            {**result, "runtime_state": {**result["runtime_state"], "cycle_count": 1}},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "state id",
        ),
        (
            {
                **result,
                "execution_plan": {
                    **result["execution_plan"],
                    "starts_process": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "process side effect",
        ),
        (
            {
                **result,
                "guardrails": {
                    **result["guardrails"],
                    "process_started": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "process side effect",
        ),
        (
            {
                **result,
                "metadata": {
                    **result["metadata"],
                    "database_write_performed": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "metadata",
        ),
        (
            {**result, "daemon_supervisor_result_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "id",
        ),
        (
            {**result, "raw_payload": {"secret": "value"}},
            "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_supervisor_result(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


def test_supervisor_result_supports_explicit_failed_status_without_side_effects() -> None:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        checked_at=CHECKED_AT,
    )
    result = build_artifact_retention_scheduler_daemon_supervisor_result(
        supervisor_command=command,
        result_status="failed",
        observed_at=OBSERVED_AT,
        message="simulated supervisor status failure",
    )

    assert result["result_status"] == "FAILED"
    assert result["decision_reason"] == "supervisor_result_failed"
    assert result["execution_plan"]["starts_process"] is False
    assert result["guardrails"]["database_write_performed"] is False
    assert summarize_artifact_retention_scheduler_daemon_supervisor_result(result)[
        "database_write_performed"
    ] is False


def test_fake_supervisor_adapter_invokes_without_process_side_effects() -> None:
    adapter = FakeArtifactRetentionSchedulerDaemonSupervisorAdapter()
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="start_daemon",
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        max_cycles=2,
    )

    result = run_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command=command,
        supervisor_adapter=adapter,
        observed_at=OBSERVED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_supervisor_result(
        result
    )

    assert adapter.adapter_name == (
        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ADAPTER_NAME
    )
    assert result["result_status"] == "BLOCKED"
    assert result["decision_reason"] == "fake_supervisor_dry_run_start_blocked"
    assert result["execution_plan"]["supervisor_adapter_available"] is True
    assert result["execution_plan"]["supervisor_adapter_invoked"] is True
    assert result["execution_plan"]["start_blocked_by_fake_supervisor"] is True
    assert result["execution_plan"]["starts_process"] is False
    assert result["guardrails"]["fake_supervisor_adapter_only"] is True
    assert result["metadata"]["adapter_name"] == (
        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_ADAPTER_NAME
    )
    assert summary["supervisor_adapter_invoked"] is True
    assert summary["process_started"] is False
    assert "adapter_invoked=1" in supervisor_result_summary_line(result)


def test_fake_supervisor_adapter_status_and_stop_outcomes() -> None:
    adapter = FakeArtifactRetentionSchedulerDaemonSupervisorAdapter()
    status_command = build_artifact_retention_scheduler_daemon_supervisor_command(
        checked_at=CHECKED_AT,
    )
    stop_command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="stop_daemon",
        checked_at=CHECKED_AT,
    )

    status_result = run_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command=status_command,
        supervisor_adapter=adapter,
        observed_at=OBSERVED_AT,
    )
    stop_result = run_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command=stop_command,
        supervisor_adapter=adapter,
        observed_at=OBSERVED_AT,
    )
    default_result = run_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command=status_command,
        observed_at=OBSERVED_AT,
    )

    assert status_result["result_status"] == "READY"
    assert status_result["decision_reason"] == "fake_supervisor_status_probe"
    assert status_result["metadata"]["supervisor_adapter_invoked"] is True
    assert stop_result["result_status"] == "NOOP"
    assert stop_result["decision_reason"] == "fake_supervisor_dry_run_stop_noop"
    assert stop_result["execution_plan"]["stop_noop_by_fake_supervisor"] is True
    assert default_result["decision_reason"] == "status_probe_metadata_only"
    assert default_result["metadata"]["supervisor_adapter_invoked"] is False


def test_supervisor_command_rejects_unsafe_actor_and_builder_edges() -> None:
    with pytest.raises(ArtifactHandoffError) as actor_exc:
        build_artifact_retention_scheduler_daemon_supervisor_command(
            checked_at=CHECKED_AT,
            requested_by={"actor_type": "operator"},
        )
    assert actor_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid"
    )
    assert "actor_id" in actor_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as mode_exc:
        build_artifact_retention_scheduler_daemon_supervisor_command(
            checked_at=CHECKED_AT,
            supervisor_mode="systemd",
        )
    assert "mode" in mode_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as result_status_exc:
        build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=build_artifact_retention_scheduler_daemon_supervisor_command(
                checked_at=CHECKED_AT,
            ),
            result_status="started",
            observed_at=OBSERVED_AT,
        )
    assert result_status_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_supervisor_result_invalid"
    )

    with pytest.raises(ArtifactHandoffError) as unavailable_invoked_exc:
        build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=build_artifact_retention_scheduler_daemon_supervisor_command(
                checked_at=CHECKED_AT,
            ),
            observed_at=OBSERVED_AT,
            supervisor_adapter_invoked=True,
        )
    assert "availability" in unavailable_invoked_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as missing_name_exc:
        build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=build_artifact_retention_scheduler_daemon_supervisor_command(
                checked_at=CHECKED_AT,
            ),
            observed_at=OBSERVED_AT,
            supervisor_adapter_available=True,
        )
    assert "adapter name is required" in missing_name_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as process_side_effect_exc:
        build_artifact_retention_scheduler_daemon_supervisor_result(
            supervisor_command=build_artifact_retention_scheduler_daemon_supervisor_command(
                checked_at=CHECKED_AT,
            ),
            observed_at=OBSERVED_AT,
            process_started=True,
        )
    assert "process side effect" in process_side_effect_exc.value.detail


def test_supervisor_command_accepts_config_with_job_queue_without_using_it() -> None:
    queue = InMemoryJobQueue()

    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action="start_daemon",
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
    )

    assert command["execution_plan"]["enqueues_job_queue"] is False
    assert command["metadata"]["job_queue_enqueue_performed"] is False
    assert queue.list_jobs() == []
