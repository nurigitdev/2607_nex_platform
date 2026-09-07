from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_MODE,
    build_artifact_retention_scheduler_daemon_supervised_process_snapshot,
    build_artifact_retention_scheduler_daemon_supervisor_command,
    summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot,
    supervised_process_snapshot_summary_line,
    validate_artifact_retention_scheduler_daemon_supervised_process_snapshot,
)
from nex_ae_api.artifacts import ArtifactHandoffError


CHECKED_AT = "2026-09-08T01:00:00Z"
OBSERVED_AT = "2026-09-08T01:00:05Z"
STARTED_AT = "2026-09-08T01:00:10Z"
COMPLETED_AT = "2026-09-08T01:00:20Z"


def _command(
    action: str = "status_probe",
    *,
    enabled: bool = False,
    explicit_opt_in: bool = False,
    max_cycles: int | str = 1,
    run_worker: bool = False,
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_supervisor_command(
        action=action,
        enabled=enabled,
        explicit_opt_in=explicit_opt_in,
        checked_at=CHECKED_AT,
        max_cycles=max_cycles,
        run_worker=run_worker,
    )


def test_supervised_process_status_probe_defaults_to_missing_metadata_only() -> None:
    command = _command()
    snapshot = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=command,
        observed_at=OBSERVED_AT,
        message="operator status probe",
    )
    summary = summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    )
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

    assert snapshot["daemon_supervised_process_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION
    )
    assert snapshot["service_id"] == "nex-ae-api"
    assert snapshot["scheduler_id"] == command["scheduler_id"]
    assert snapshot["daemon_supervisor_command_id"] == (
        command["daemon_supervisor_command_id"]
    )
    assert snapshot["action"] == "status_probe"
    assert snapshot["process_mode"] == (
        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_MODE
    )
    assert snapshot["process"] == {
        "process_id": None,
        "host_id": "localhost",
        "entrypoint": DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ENTRYPOINT,
        "supervisor_mode": "fake_dry_run",
        "max_cycles": 1,
        "run_worker": False,
        "output_format": "json",
    }
    assert snapshot["lifecycle"] == {
        "process_status": "MISSING",
        "observed_at": OBSERVED_AT,
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "termination_signal": None,
    }
    assert snapshot["guardrails"]["metadata_only"] is True
    assert snapshot["guardrails"]["subprocess_adapter_required"] is False
    assert snapshot["guardrails"]["contract_starts_process"] is False
    assert snapshot["guardrails"]["contract_stops_process"] is False
    assert snapshot["guardrails"]["ag_direct_process_control_allowed"] is False
    assert snapshot["metadata"]["safe_for_ag_projection"] is True
    assert snapshot["metadata"]["message"] == "operator status probe"
    assert snapshot["metadata"]["process_running"] is False
    assert summary["process_status"] == "MISSING"
    assert summary["process_id"] is None
    assert "process_id=none" in supervised_process_snapshot_summary_line(snapshot)
    assert validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    ) == snapshot
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


def test_supervised_process_start_snapshot_is_start_requested_until_adapter_runs() -> None:
    command = _command(
        "start_daemon",
        enabled=True,
        explicit_opt_in=True,
        max_cycles="3",
        run_worker=True,
    )
    snapshot = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=command,
        observed_at=OBSERVED_AT,
        host_id="ae-node-01",
    )

    assert snapshot["action"] == "start_daemon"
    assert snapshot["process"]["process_id"] is None
    assert snapshot["process"]["host_id"] == "ae-node-01"
    assert snapshot["process"]["max_cycles"] == 3
    assert snapshot["process"]["run_worker"] is True
    assert snapshot["lifecycle"]["process_status"] == "START_REQUESTED"
    assert snapshot["guardrails"]["subprocess_adapter_required"] is True
    assert snapshot["guardrails"]["explicit_opt_in_required"] is True
    assert snapshot["guardrails"]["production_continuous_start_enabled"] is False
    assert snapshot["metadata"]["process_started_observed"] is False


def test_supervised_process_running_snapshot_records_pid_without_starting_process() -> None:
    command = _command(
        "start_daemon",
        enabled=True,
        explicit_opt_in=True,
        max_cycles=2,
    )
    snapshot = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=command,
        process_status="running",
        process_id="4321",
        host_id="ae-node-01",
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        snapshot
    )

    assert snapshot["lifecycle"]["process_status"] == "RUNNING"
    assert snapshot["process"]["process_id"] == 4321
    assert snapshot["guardrails"]["process_running_observed"] is True
    assert snapshot["metadata"]["process_running"] is True
    assert snapshot["metadata"]["process_started_observed"] is True
    assert snapshot["metadata"]["process_stopped_observed"] is False
    assert summary["process_id"] == 4321
    assert "status=RUNNING" in supervised_process_snapshot_summary_line(snapshot)
    assert "running=1" in supervised_process_snapshot_summary_line(snapshot)


def test_supervised_process_stop_and_exit_snapshots_capture_terminal_metadata() -> None:
    stop_command = _command("stop_daemon")
    stopped = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=stop_command,
        process_status="STOPPED",
        process_id=4321,
        host_id="ae-node-01",
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        termination_signal="SIGTERM",
    )
    status_command = _command()
    exited = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=status_command,
        process_status="EXITED",
        process_id=4321,
        host_id="ae-node-01",
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        exit_code="0",
    )

    assert stopped["lifecycle"]["termination_signal"] == "SIGTERM"
    assert stopped["metadata"]["process_stopped_observed"] is True
    assert stopped["metadata"]["termination_signal_observed"] is True
    assert exited["lifecycle"]["exit_code"] == 0
    assert exited["metadata"]["process_exit_observed"] is True
    assert exited["metadata"]["process_stopped_observed"] is True


@pytest.mark.parametrize(
    ("mutate", "expected_detail"),
    (
        (lambda snapshot: [], "object"),
        (
            lambda snapshot: {
                **snapshot,
                "daemon_supervised_process_schema_version": "wrong",
            },
            "schema",
        ),
        (lambda snapshot: {**snapshot, "service_id": "nex-ag"}, "service id"),
        (lambda snapshot: {**snapshot, "process_mode": "continuous"}, "mode"),
        (lambda snapshot: {**snapshot, "scheduler_id": " "}, "scheduler_id"),
        (
            lambda snapshot: {
                **snapshot,
                "daemon_supervisor_command_id": "",
            },
            "daemon_supervisor_command_id",
        ),
        (lambda snapshot: {**snapshot, "action": "launch"}, "action"),
        (lambda snapshot: {**snapshot, "process": "bad"}, "process payload"),
        (
            lambda snapshot: {
                **snapshot,
                "process": {**snapshot["process"], "unexpected": True},
            },
            "process payload keys",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "process": {**snapshot["process"], "process_id": 0},
            },
            "positive integer",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "process": {**snapshot["process"], "host_id": ""},
            },
            "host_id",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "process": {**snapshot["process"], "max_cycles": 0},
            },
            "positive integer",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "process": {**snapshot["process"], "run_worker": "yes"},
            },
            "boolean",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "process": {**snapshot["process"], "output_format": "xml"},
            },
            "output format",
        ),
        (lambda snapshot: {**snapshot, "lifecycle": "bad"}, "lifecycle"),
        (
            lambda snapshot: {
                **snapshot,
                "lifecycle": {**snapshot["lifecycle"], "x": True},
            },
            "lifecycle keys",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "lifecycle": {
                    **snapshot["lifecycle"],
                    "process_status": "PAUSED",
                },
            },
            "status",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "lifecycle": {**snapshot["lifecycle"], "observed_at": ""},
            },
            "observed_at",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "lifecycle": {**snapshot["lifecycle"], "exit_code": True},
            },
            "exit code",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "guardrails": {**snapshot["guardrails"], "metadata_only": False},
            },
            "guardrails",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "metadata": {
                    **snapshot["metadata"],
                    "process_running": True,
                },
            },
            "metadata",
        ),
        (
            lambda snapshot: {
                **snapshot,
                "daemon_supervised_process_id": "wrong",
            },
            "id",
        ),
    ),
)
def test_supervised_process_snapshot_validation_edges(
    mutate: object,
    expected_detail: str,
) -> None:
    snapshot = build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=_command(),
        observed_at=OBSERVED_AT,
    )
    invalid = mutate(deepcopy(snapshot))

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_supervised_process_snapshot(
            invalid
        )

    assert exc_info.value.error_code in {
        "ae.artifact_retention_scheduler_daemon_supervised_process_invalid",
        "ae.artifact_retention_scheduler_daemon_supervised_process_schema_invalid",
    }
    assert expected_detail in exc_info.value.detail


@pytest.mark.parametrize(
    ("action", "kwargs", "expected_detail"),
    (
        ("status_probe", {"process_status": "MISSING", "process_id": 77}, "must not be present"),
        ("start_daemon", {"process_status": "RUNNING"}, "id is required"),
        (
            "start_daemon",
            {"process_status": "RUNNING", "process_id": 77},
            "timestamps are invalid",
        ),
        (
            "stop_daemon",
            {
                "process_status": "STOPPED",
                "process_id": 77,
                "started_at": STARTED_AT,
                "completed_at": COMPLETED_AT,
            },
            "stopped supervised process metadata",
        ),
        (
            "status_probe",
            {
                "process_status": "EXITED",
                "process_id": 77,
                "started_at": STARTED_AT,
                "completed_at": COMPLETED_AT,
            },
            "exited supervised process metadata",
        ),
        (
            "status_probe",
            {
                "process_status": "EXITED",
                "process_id": 77,
                "started_at": STARTED_AT,
                "completed_at": COMPLETED_AT,
                "exit_code": 512,
            },
            "supported range",
        ),
        (
            "start_daemon",
            {
                "process_status": "START_REQUESTED",
                "started_at": STARTED_AT,
            },
            "inactive supervised process timestamps",
        ),
        (
            "start_daemon",
            {
                "process_status": "START_REQUESTED",
                "termination_signal": "SIGTERM",
            },
            "termination signal",
        ),
        (
            "start_daemon",
            {"process_status": "RUNNING", "process_id": 77, "exit_code": 0},
            "active supervised process timestamps",
        ),
    ),
)
def test_supervised_process_snapshot_rejects_inconsistent_lifecycle(
    action: str,
    kwargs: dict[str, object],
    expected_detail: str,
) -> None:
    command = (
        _command("start_daemon", enabled=True, explicit_opt_in=True)
        if action == "start_daemon"
        else _command(action)
    )
    with pytest.raises(ArtifactHandoffError) as exc_info:
        build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
            supervisor_command=command,
            observed_at=OBSERVED_AT,
            **kwargs,
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_supervised_process_invalid"
    )
    assert expected_detail in exc_info.value.detail


def test_supervised_process_snapshot_rejects_action_status_mismatch() -> None:
    stop_command = _command("stop_daemon")

    with pytest.raises(ArtifactHandoffError) as exc_info:
        build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
            supervisor_command=stop_command,
            process_status="RUNNING",
            process_id=77,
            observed_at=OBSERVED_AT,
            started_at=STARTED_AT,
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_supervised_process_invalid"
    )
    assert "action and status" in exc_info.value.detail
