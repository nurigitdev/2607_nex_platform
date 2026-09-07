from __future__ import annotations

import json

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCOPE,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STATUS,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION,
    MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES,
    MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID,
    MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STALE_AFTER_SECONDS,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE,
    build_artifact_retention_scheduler_daemon_cli_execute_command,
    build_artifact_retention_scheduler_daemon_process_lock,
    build_artifact_retention_scheduler_daemon_run_metadata,
    process_lock_summary_line,
    run_metadata_summary_line,
    summarize_artifact_retention_scheduler_daemon_process_lock,
    summarize_artifact_retention_scheduler_daemon_run_metadata,
    validate_artifact_retention_scheduler_daemon_process_lock,
    validate_artifact_retention_scheduler_daemon_run_metadata,
)
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    build_artifact_retention_scheduler_config,
)


CHECKED_AT = "2026-08-31T17:30:00Z"
STARTED_AT = "2026-08-31T17:31:00Z"
COMPLETED_AT = "2026-08-31T17:32:00Z"


def _execute_command(max_cycles: int = 2) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_cli_execute_command(
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        max_cycles=max_cycles,
        run_worker=True,
        output_format="summary",
    )


def _process_lock() -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=_execute_command(),
        process_id="4242",
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
        stale_after_seconds="900",
    )


def test_artifact_retention_scheduler_daemon_process_lock_contract() -> None:
    execute_command = _execute_command()
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id="4242",
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
        stale_after_seconds="900",
    )
    default_pid_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        host_id="ae-node-default",
        requested_at=CHECKED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_process_lock(
        process_lock
    )
    serialized = json.dumps(process_lock, ensure_ascii=False, sort_keys=True)

    assert process_lock["daemon_process_lock_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION
    )
    assert process_lock["service_id"] == "nex-ae-api"
    assert process_lock["scheduler_id"] == execute_command["scheduler_id"]
    assert process_lock["daemon_cli_execute_command_id"] == (
        execute_command["daemon_cli_execute_command_id"]
    )
    assert process_lock["lock_scope"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCOPE
    )
    assert process_lock["lock_status"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STATUS
    )
    assert process_lock["process"] == {
        "process_id": 4242,
        "host_id": "ae-node-01",
        "lock_owner": (
            "ae-artifact-retention-scheduler-local-v1:ae-node-01:4242"
        ),
        "entrypoint": "python -m nex_ae_api.artifact_retention_scheduler_daemon",
    }
    assert default_pid_lock["process"]["process_id"] > 0
    assert process_lock["timing"] == {
        "requested_at": CHECKED_AT,
        "stale_after_seconds": 900,
    }
    assert process_lock["command_summary"] == {
        "mode": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_MODE,
        "max_cycles": 2,
        "run_worker": True,
        "plan_only": False,
    }
    assert process_lock["guardrails"]["metadata_only"] is True
    assert process_lock["guardrails"]["process_lock_required"] is True
    assert process_lock["guardrails"]["process_lock_acquired"] is False
    assert process_lock["guardrails"]["database_write_performed"] is False
    assert process_lock["guardrails"]["physical_delete_automation_enabled"] is False
    assert process_lock["metadata"]["safe_for_ag_projection"] is True
    assert process_lock["metadata"]["process_id"] == 4242
    assert process_lock["metadata"]["execute_mode"] is True
    assert process_lock["metadata"]["process_lock_acquired"] is False
    assert summary["process_id"] == 4242
    assert summary["stale_after_seconds"] == 900
    assert summary["process_lock_acquired"] is False
    assert validate_artifact_retention_scheduler_daemon_process_lock(
        process_lock
    ) == process_lock
    assert "ae_scheduler_daemon_process_lock=pass" in (
        process_lock_summary_line(process_lock)
    )
    assert "acquired=0" in process_lock_summary_line(process_lock)
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_process_lock_validation_edges() -> None:
    process_lock = _process_lock()

    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "object",
        ),
        (
            {**process_lock, "daemon_process_lock_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_process_lock_schema_invalid",
            "schema",
        ),
        (
            {**process_lock, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "service id",
        ),
        (
            {**process_lock, "scheduler_id": " "},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "scheduler_id",
        ),
        (
            {**process_lock, "daemon_cli_execute_command_id": ""},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "daemon_cli_execute_command_id",
        ),
        (
            {**process_lock, "lock_scope": "other"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "scope",
        ),
        (
            {**process_lock, "lock_status": "ACQUIRED"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "status",
        ),
        (
            {**process_lock, "process": "bad"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "process",
        ),
        (
            {**process_lock, "process": {**process_lock["process"], "x": True}},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "process keys",
        ),
        (
            {
                **process_lock,
                "process": {**process_lock["process"], "process_id": 0},
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "positive integer",
        ),
        (
            {
                **process_lock,
                "process": {
                    **process_lock["process"],
                    "process_id": (
                        MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_ID + 1
                    ),
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "supported maximum",
        ),
        (
            {**process_lock, "process": {**process_lock["process"], "host_id": ""}},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "host_id",
        ),
        (
            {
                **process_lock,
                "process": {**process_lock["process"], "lock_owner": "wrong"},
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "owner",
        ),
        (
            {
                **process_lock,
                "process": {**process_lock["process"], "entrypoint": "python x.py"},
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "entrypoint",
        ),
        (
            {**process_lock, "timing": "bad"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "timing",
        ),
        (
            {**process_lock, "timing": {**process_lock["timing"], "x": True}},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "timing keys",
        ),
        (
            {**process_lock, "timing": {**process_lock["timing"], "requested_at": " "}},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "requested_at",
        ),
        (
            {
                **process_lock,
                "timing": {**process_lock["timing"], "stale_after_seconds": 0},
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "positive integer",
        ),
        (
            {
                **process_lock,
                "timing": {
                    **process_lock["timing"],
                    "stale_after_seconds": (
                        MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_STALE_AFTER_SECONDS
                        + 1
                    ),
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "supported maximum",
        ),
        (
            {**process_lock, "command_summary": "bad"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "command summary",
        ),
        (
            {
                **process_lock,
                "command_summary": {
                    **process_lock["command_summary"],
                    "unexpected": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "command summary keys",
        ),
        (
            {
                **process_lock,
                "command_summary": {**process_lock["command_summary"], "mode": "plan"},
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "mode",
        ),
        (
            {
                **process_lock,
                "command_summary": {
                    **process_lock["command_summary"],
                    "max_cycles": (
                        MAX_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_MAX_CYCLES
                        + 1
                    ),
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "supported maximum",
        ),
        (
            {
                **process_lock,
                "command_summary": {
                    **process_lock["command_summary"],
                    "run_worker": "true",
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "run_worker",
        ),
        (
            {
                **process_lock,
                "command_summary": {
                    **process_lock["command_summary"],
                    "plan_only": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "execute mode",
        ),
        (
            {
                **process_lock,
                "guardrails": {
                    **process_lock["guardrails"],
                    "process_lock_acquired": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "guardrails",
        ),
        (
            {
                **process_lock,
                "metadata": {**process_lock["metadata"], "database_url_included": True},
            },
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "metadata",
        ),
        (
            {**process_lock, "daemon_process_lock_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "lock id",
        ),
        (
            {**process_lock, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_process_lock_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_process_lock(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as process_exc:
        build_artifact_retention_scheduler_daemon_process_lock(
            execute_command=_execute_command(),
            process_id=False,
        )
    assert process_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_process_lock_invalid"
    )


def test_artifact_retention_scheduler_daemon_run_metadata_contract() -> None:
    execute_command = _execute_command()
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )

    pending = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
    )
    running = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
        run_status="running",
        started_at=STARTED_AT,
    )
    succeeded = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
        run_status="SUCCEEDED",
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )
    pending_summary = summarize_artifact_retention_scheduler_daemon_run_metadata(
        pending
    )
    serialized = json.dumps(pending, ensure_ascii=False, sort_keys=True)

    assert pending["daemon_run_metadata_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION
    )
    assert pending["service_id"] == "nex-ae-api"
    assert pending["scheduler_id"] == execute_command["scheduler_id"]
    assert pending["daemon_cli_execute_command_id"] == (
        execute_command["daemon_cli_execute_command_id"]
    )
    assert pending["daemon_process_lock_id"] == (
        process_lock["daemon_process_lock_id"]
    )
    assert pending["process"] == process_lock["process"]
    assert pending["command_summary"] == process_lock["command_summary"]
    assert pending["lifecycle"] == {
        "run_status": "PENDING",
        "requested_at": CHECKED_AT,
        "started_at": None,
        "completed_at": None,
    }
    assert pending["guardrails"]["metadata_only"] is True
    assert pending["guardrails"]["run_record_required"] is True
    assert pending["guardrails"]["run_record_persisted"] is False
    assert pending["guardrails"]["lifecycle_event_persisted"] is False
    assert pending["guardrails"]["database_write_performed"] is False
    assert pending["metadata"]["run_started"] is False
    assert pending["metadata"]["run_completed"] is False
    assert running["lifecycle"]["run_status"] == "RUNNING"
    assert running["metadata"]["run_started"] is True
    assert running["metadata"]["run_completed"] is False
    assert succeeded["lifecycle"]["run_status"] == "SUCCEEDED"
    assert succeeded["metadata"]["run_completed"] is True
    assert pending_summary["run_status"] == "PENDING"
    assert pending_summary["process_id"] == 4242
    assert pending_summary["run_record_persisted"] is False
    assert validate_artifact_retention_scheduler_daemon_run_metadata(pending) == (
        pending
    )
    assert "ae_scheduler_daemon_run_metadata=pass" in (
        run_metadata_summary_line(pending)
    )
    assert "persisted=0" in run_metadata_summary_line(pending)
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_run_metadata_validation_edges() -> None:
    execute_command = _execute_command()
    process_lock = _process_lock()
    run_metadata = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
    )

    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "object",
        ),
        (
            {**run_metadata, "daemon_run_metadata_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_schema_invalid",
            "schema",
        ),
        (
            {**run_metadata, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "service id",
        ),
        (
            {**run_metadata, "scheduler_id": ""},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "scheduler_id",
        ),
        (
            {**run_metadata, "daemon_cli_execute_command_id": " "},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "daemon_cli_execute_command_id",
        ),
        (
            {**run_metadata, "daemon_process_lock_id": ""},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "daemon_process_lock_id",
        ),
        (
            {**run_metadata, "process": "bad"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "process",
        ),
        (
            {
                **run_metadata,
                "process": {**run_metadata["process"], "process_id": 0},
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "positive integer",
        ),
        (
            {**run_metadata, "command_summary": "bad"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "command summary",
        ),
        (
            {
                **run_metadata,
                "command_summary": {
                    **run_metadata["command_summary"],
                    "plan_only": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "execute mode",
        ),
        (
            {**run_metadata, "lifecycle": "bad"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "lifecycle",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {**run_metadata["lifecycle"], "x": True},
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "lifecycle keys",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {**run_metadata["lifecycle"], "run_status": "MAYBE"},
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "run status",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {**run_metadata["lifecycle"], "started_at": STARTED_AT},
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "pending run timestamps",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {
                    **run_metadata["lifecycle"],
                    "run_status": "RUNNING",
                },
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "active run timestamps",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {
                    **run_metadata["lifecycle"],
                    "run_status": "STOPPING",
                    "started_at": STARTED_AT,
                    "completed_at": COMPLETED_AT,
                },
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "active run timestamps",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {
                    **run_metadata["lifecycle"],
                    "run_status": "SUCCEEDED",
                    "started_at": STARTED_AT,
                },
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "completed run timestamps",
        ),
        (
            {
                **run_metadata,
                "lifecycle": {
                    **run_metadata["lifecycle"],
                    "run_status": "FAILED",
                    "completed_at": COMPLETED_AT,
                },
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "completed run timestamps",
        ),
        (
            {
                **run_metadata,
                "guardrails": {
                    **run_metadata["guardrails"],
                    "run_record_persisted": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "guardrails",
        ),
        (
            {
                **run_metadata,
                "metadata": {**run_metadata["metadata"], "database_url_included": True},
            },
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "metadata",
        ),
        (
            {**run_metadata, "daemon_run_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "metadata id",
        ),
        (
            {**run_metadata, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_run_metadata_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_run_metadata(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    other_command = _execute_command(max_cycles=3)
    other_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=other_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    with pytest.raises(ArtifactHandoffError) as scope_exc:
        build_artifact_retention_scheduler_daemon_run_metadata(
            execute_command=execute_command,
            process_lock=other_lock,
        )
    assert scope_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_run_metadata_invalid"
    )
    assert "command scope" in scope_exc.value.detail

    other_scheduler_config = {
        **build_artifact_retention_scheduler_config(),
        "scheduler_id": "other-ae-artifact-retention-scheduler",
    }
    other_scheduler_command = (
        build_artifact_retention_scheduler_daemon_cli_execute_command(
            scheduler_config=other_scheduler_config,
            enabled=True,
            explicit_opt_in=True,
            checked_at=CHECKED_AT,
        )
    )
    other_scheduler_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=other_scheduler_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    with pytest.raises(ArtifactHandoffError) as scheduler_scope_exc:
        build_artifact_retention_scheduler_daemon_run_metadata(
            execute_command=execute_command,
            process_lock=other_scheduler_lock,
        )
    assert scheduler_scope_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_run_metadata_invalid"
    )
    assert "metadata scope" in scheduler_scope_exc.value.detail
