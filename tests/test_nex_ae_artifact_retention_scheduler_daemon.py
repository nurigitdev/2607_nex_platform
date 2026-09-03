from __future__ import annotations

import io
import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_PLAN_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
    MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
    build_artifact_retention_scheduler_daemon_cli_plan,
    main,
    summarize_artifact_retention_scheduler_daemon_cli_plan,
    summary_line,
    validate_artifact_retention_scheduler_daemon_cli_plan,
)
from nex_ae_api.artifact_retention_scheduler import (
    build_artifact_retention_scheduler_daemon_runtime_state,
)
from nex_ae_api.artifacts import ArtifactHandoffError
from nex_ae_api.artifacts import build_artifact_retention_scheduler_config
from nex_runtime import InMemoryJobQueue


CHECKED_AT = "2026-08-31T17:30:00Z"


def test_artifact_retention_scheduler_daemon_cli_plan_defaults() -> None:
    plan = build_artifact_retention_scheduler_daemon_cli_plan(
        checked_at=CHECKED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_cli_plan(plan)
    serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)

    assert plan["daemon_cli_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_PLAN_SCHEMA_VERSION
    )
    assert plan["service_id"] == "nex-ae-api"
    assert plan["scheduler_id"] == "ae-artifact-retention-scheduler-local-v1"
    assert plan["command"] == {
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "profile": "test",
        "enabled": False,
        "explicit_opt_in": False,
        "checked_at": CHECKED_AT,
        "max_cycles": 1,
        "run_worker": False,
        "output_format": "json",
        "plan_only": True,
    }
    assert plan["runtime_state"]["lifecycle_status"] == "DISABLED"
    assert plan["runtime_state"]["lifecycle_reason"] == "runtime_disabled"
    assert plan["execution_plan"] == {
        "loads_runtime_config": True,
        "validates_daemon_config": True,
        "builds_runtime_state": True,
        "ready_to_start": False,
        "plan_only": True,
        "starts_bounded_loop": False,
        "runs_tick_once": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "worker_requested_for_future_loop": False,
        "writes_database": False,
        "physical_delete_enabled": False,
    }
    assert plan["guardrails"] == {
        "metadata_only": True,
        "plan_only": True,
        "daemon_process_owner_ae": True,
        "bounded_loop_available": False,
        "bounded_loop_started": False,
        "database_url_required": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted": False,
        "physical_delete_automation_enabled": False,
        "secrets_redacted": True,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }
    assert plan["metadata"]["metadata_only"] is True
    assert plan["metadata"]["ready_to_start"] is False
    assert plan["metadata"]["blocked_by_runtime"] is True
    assert plan["metadata"]["bounded_loop_started"] is False
    assert plan["metadata"]["job_enqueued"] is False
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "profile": "test",
        "max_cycles": 1,
        "run_worker": False,
        "output_format": "json",
        "plan_only": True,
        "ready_to_start": False,
        "blocked_by_runtime": True,
        "lifecycle_status": "DISABLED",
        "lifecycle_reason": "runtime_disabled",
        "bounded_loop_started": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
    }
    assert validate_artifact_retention_scheduler_daemon_cli_plan(plan) == plan
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_cli_plan_ready_plan_only() -> None:
    scheduler_config = build_artifact_retention_scheduler_config(
        job_queue=InMemoryJobQueue()
    )

    plan = build_artifact_retention_scheduler_daemon_cli_plan(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        interval_seconds="120",
        jitter_seconds="10",
        backoff_seconds="30",
        max_cycles="3",
        run_worker=True,
        output_format="summary",
    )

    assert plan["command"]["max_cycles"] == 3
    assert plan["command"]["run_worker"] is True
    assert plan["command"]["output_format"] == "summary"
    assert plan["runtime_config"]["enablement"]["enablement_status"] == "READY"
    assert plan["runtime_state"]["lifecycle_status"] == "STARTING"
    assert plan["runtime_state"]["lifecycle_reason"] == "start_requested"
    assert plan["execution_plan"]["ready_to_start"] is True
    assert plan["execution_plan"]["worker_requested_for_future_loop"] is True
    assert plan["execution_plan"]["starts_bounded_loop"] is False
    assert plan["metadata"]["ready_to_start"] is True
    assert plan["metadata"]["blocked_by_runtime"] is False
    assert plan["metadata"]["summary_requested"] is True
    assert plan["metadata"]["lifecycle_starting"] is True
    assert "lifecycle=STARTING" in summary_line(plan)
    assert "max_cycles=3" in summary_line(plan)


def test_artifact_retention_scheduler_daemon_cli_plan_validation_edges() -> None:
    plan = build_artifact_retention_scheduler_daemon_cli_plan(
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        max_cycles=2,
    )
    bad_state = deepcopy(plan["runtime_state"])
    bad_state["lifecycle_status"] = "DISABLED"
    bad_command = {**plan["command"], "plan_only": False}
    valid_disabled_ready_state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=build_artifact_retention_scheduler_config(),
        runtime_config=plan["runtime_config"],
        daemon_config=plan["daemon_config"],
        lifecycle_status="DISABLED",
        lifecycle_reason="runtime_disabled",
        observed_at=CHECKED_AT,
    )

    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "object",
        ),
        (
            {**plan, "daemon_cli_plan_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_plan_schema_invalid",
            "schema",
        ),
        (
            {**plan, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "service id",
        ),
        (
            {**plan, "scheduler_id": " "},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "scheduler_id",
        ),
        (
            {**plan, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "scope",
        ),
        (
            {**plan, "command": "bad"},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "command",
        ),
        (
            {**plan, "command": {**plan["command"], "unexpected": True}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "command keys",
        ),
        (
            {**plan, "command": {**plan["command"], "entrypoint": "python daemon.py"}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "entrypoint",
        ),
        (
            {**plan, "command": {**plan["command"], "max_cycles": 0}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "positive integer",
        ),
        (
            {**plan, "command": {**plan["command"], "max_cycles": True}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "positive integer",
        ),
        (
            {**plan, "command": {**plan["command"], "max_cycles": "bad"}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "positive integer",
        ),
        (
            {
                **plan,
                "command": {
                    **plan["command"],
                    "max_cycles": (
                        MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES
                        + 1
                    ),
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "supported maximum",
        ),
        (
            {**plan, "command": {**plan["command"], "run_worker": "yes"}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "run_worker",
        ),
        (
            {**plan, "command": {**plan["command"], "output_format": "yaml"}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "output format",
        ),
        (
            {**plan, "command": bad_command},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "plan-only",
        ),
        (
            {
                **plan,
                "runtime_config": {
                    **plan["runtime_config"],
                    "service_id": "nex-ag",
                },
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "service id",
        ),
        (
            {
                **plan,
                "daemon_config": {
                    **plan["daemon_config"],
                    "scheduler_id": "other-scheduler",
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "daemon scope",
        ),
        (
            {**plan, "runtime_state": bad_state},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "disabled state reason",
        ),
        (
            {**plan, "runtime_state": valid_disabled_ready_state},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "state lifecycle",
        ),
        (
            {
                **plan,
                "command": {
                    **plan["command"],
                    "profile": "other",
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "profile",
        ),
        (
            {
                **plan,
                "command": {
                    **plan["command"],
                    "enabled": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "enabled flag",
        ),
        (
            {
                **plan,
                "command": {
                    **plan["command"],
                    "explicit_opt_in": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "explicit opt-in",
        ),
        (
            {
                **plan,
                "command": {
                    **plan["command"],
                    "checked_at": "2026-08-31T17:31:00Z",
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "checked_at",
        ),
        (
            {**plan, "execution_plan": {**plan["execution_plan"], "runs_tick_once": True}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "execution plan",
        ),
        (
            {**plan, "guardrails": {**plan["guardrails"], "bounded_loop_started": True}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "guardrails",
        ),
        (
            {**plan, "metadata": {**plan["metadata"], "job_enqueued": True}},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "metadata",
        ),
        (
            {**plan, "daemon_cli_plan_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "plan id",
        ),
        (
            {**plan, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_cli_plan_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_cli_plan(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as output_exc:
        build_artifact_retention_scheduler_daemon_cli_plan(output_format=None)  # type: ignore[arg-type]
    assert output_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_cli_plan_invalid"
    )

    with pytest.raises(ArtifactHandoffError) as max_cycle_exc:
        build_artifact_retention_scheduler_daemon_cli_plan(max_cycles=False)
    assert max_cycle_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_cli_plan_invalid"
    )


def test_artifact_retention_scheduler_daemon_cli_main_outputs() -> None:
    summary_stream = io.StringIO()
    json_stream = io.StringIO()

    assert main(
        [
            "--summary",
            "--enabled",
            "--explicit-opt-in",
            "--checked-at",
            CHECKED_AT,
            "--max-cycles",
            "2",
        ],
        out=summary_stream,
    ) == 0
    assert "ae_scheduler_daemon_cli_plan=pass" in summary_stream.getvalue()
    assert "lifecycle=STARTING" in summary_stream.getvalue()
    assert "bounded_loop_started=0" in summary_stream.getvalue()

    assert main(["--checked-at", CHECKED_AT], out=json_stream) == 0
    payload = json.loads(json_stream.getvalue())
    assert payload["command"]["output_format"] == "json"
    assert payload["runtime_state"]["lifecycle_status"] == "DISABLED"


def test_artifact_retention_scheduler_daemon_cli_main_reports_error() -> None:
    stream = io.StringIO()

    assert main(["--profile", "prod"], out=stream) == 1
    payload = json.loads(stream.getvalue())
    assert payload == {
        "ok": False,
        "error_code": "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
        "detail": "Artifact retention scheduler daemon runtime profile is invalid.",
    }
