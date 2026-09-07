from __future__ import annotations

import json

import pytest

from nex_ae_api import artifact_retention_scheduler_daemon as daemon_cli
from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_cli_execute_command,
    build_artifact_retention_scheduler_daemon_cli_plan,
    build_artifact_retention_scheduler_daemon_process_lock,
    build_artifact_retention_scheduler_daemon_run_metadata,
    build_artifact_retention_scheduler_daemon_signal_shutdown_adapter,
    signal_shutdown_adapter_summary_line,
    summarize_artifact_retention_scheduler_daemon_signal_shutdown_adapter,
    validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter,
)
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    build_artifact_retention_scheduler_config,
)


CHECKED_AT = "2026-08-31T17:30:00Z"
RECEIVED_AT = "2026-08-31T17:31:00Z"


def _execute_command() -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_cli_execute_command(
        enabled=True,
        explicit_opt_in=True,
        checked_at=CHECKED_AT,
        max_cycles=2,
        run_worker=True,
    )


def _process_lock() -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=_execute_command(),
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )


def _run_metadata() -> dict[str, object]:
    execute_command = _execute_command()
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    return build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
        run_status="RUNNING",
        started_at=CHECKED_AT,
    )


def _adapter() -> dict[str, object]:
    execute_command = _execute_command()
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    run_metadata = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
        run_status="RUNNING",
        started_at=CHECKED_AT,
    )
    return build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        current_state=execute_command["runtime_state"],
        process_lock=process_lock,
        run_metadata=run_metadata,
        signal_name="sigterm",
        received_at=RECEIVED_AT,
        reason="operator_requested_shutdown",
    )


def test_artifact_retention_scheduler_daemon_signal_shutdown_adapter_contract() -> None:
    adapter = _adapter()
    summary = summarize_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        adapter
    )
    serialized = json.dumps(adapter, ensure_ascii=False, sort_keys=True)

    assert adapter["daemon_signal_shutdown_adapter_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION
    )
    assert adapter["service_id"] == "nex-ae-api"
    assert adapter["signal"] == {
        "signal_name": "SIGTERM",
        "received_at": RECEIVED_AT,
        "handler": "deferred_cli_signal_adapter",
    }
    assert adapter["process"]["process_id"] == 4242
    assert adapter["run_lifecycle"]["run_status"] == "RUNNING"
    assert adapter["shutdown_transition"]["decision_status"] == "READY"
    assert adapter["shutdown_transition"]["decision_reason"] == "stop_requested"
    assert adapter["shutdown_transition"]["next_state"]["lifecycle_status"] == (
        "STOPPING"
    )
    assert adapter["execution_plan"]["signal_observed"] is True
    assert adapter["execution_plan"]["signal_handler_installed"] is False
    assert adapter["execution_plan"]["stop_signal_requested"] is True
    assert adapter["execution_plan"]["bounded_loop_should_stop_before_next_cycle"] is (
        True
    )
    assert adapter["execution_plan"]["stop_signal_delivered"] is False
    assert adapter["guardrails"]["metadata_only"] is True
    assert adapter["guardrails"]["signal_handler_installed"] is False
    assert adapter["guardrails"]["stop_signal_delivered"] is False
    assert adapter["guardrails"]["database_write_performed"] is False
    assert adapter["metadata"]["signal_name"] == "SIGTERM"
    assert adapter["metadata"]["shutdown_requested"] is True
    assert adapter["metadata"]["stop_signal_requested"] is True
    assert adapter["metadata"]["stop_signal_delivered"] is False
    assert summary["signal_name"] == "SIGTERM"
    assert summary["decision_status"] == "READY"
    assert summary["to_lifecycle_status"] == "STOPPING"
    assert summary["stop_signal_delivered"] is False
    assert validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        adapter
    ) == adapter
    assert "ae_scheduler_daemon_signal_shutdown_adapter=pass" in (
        signal_shutdown_adapter_summary_line(adapter)
    )
    assert "delivered=0" in signal_shutdown_adapter_summary_line(adapter)
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_signal_shutdown_adapter_noop_state() -> None:
    disabled_plan = build_artifact_retention_scheduler_daemon_cli_plan(
        checked_at=CHECKED_AT
    )
    execute_command = _execute_command()
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    run_metadata = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
    )

    adapter = build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
        current_state=disabled_plan["runtime_state"],
        process_lock=process_lock,
        run_metadata=run_metadata,
        signal_name="SIGINT",
        received_at=RECEIVED_AT,
    )

    assert adapter["signal"]["signal_name"] == "SIGINT"
    assert adapter["shutdown_transition"]["decision_status"] == "NOOP"
    assert adapter["shutdown_transition"]["decision_reason"] == "runtime_disabled"
    assert adapter["shutdown_transition"]["next_state"]["lifecycle_status"] == (
        "DISABLED"
    )
    assert adapter["execution_plan"]["stop_signal_requested"] is False
    assert adapter["metadata"]["shutdown_requested"] is False


def test_artifact_retention_scheduler_daemon_signal_shutdown_adapter_validation_edges() -> (
    None
):
    adapter = _adapter()

    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "object",
        ),
        (
            {**adapter, "daemon_signal_shutdown_adapter_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_schema_invalid",
            "schema",
        ),
        (
            {**adapter, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "service id",
        ),
        (
            {**adapter, "scheduler_id": ""},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "scheduler_id",
        ),
        (
            {**adapter, "daemon_run_id": " "},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "daemon_run_id",
        ),
        (
            {**adapter, "daemon_process_lock_id": ""},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "daemon_process_lock_id",
        ),
        (
            {**adapter, "daemon_cli_execute_command_id": ""},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "daemon_cli_execute_command_id",
        ),
        (
            {**adapter, "signal": "bad"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "signal",
        ),
        (
            {**adapter, "signal": {**adapter["signal"], "x": True}},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "signal keys",
        ),
        (
            {**adapter, "signal": {**adapter["signal"], "signal_name": "SIGHUP"}},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "signal",
        ),
        (
            {**adapter, "signal": {**adapter["signal"], "received_at": " "}},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "received_at",
        ),
        (
            {**adapter, "signal": {**adapter["signal"], "handler": "installed"}},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "handler",
        ),
        (
            {**adapter, "process": "bad"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "process",
        ),
        (
            {
                **adapter,
                "run_lifecycle": {**adapter["run_lifecycle"], "completed_at": CHECKED_AT},
            },
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "active run timestamps",
        ),
        (
            {**adapter, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "transition scope",
        ),
        (
            {
                **adapter,
                "execution_plan": {
                    **adapter["execution_plan"],
                    "stop_signal_delivered": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "execution plan",
        ),
        (
            {
                **adapter,
                "guardrails": {
                    **adapter["guardrails"],
                    "stop_signal_delivered": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "guardrails",
        ),
        (
            {
                **adapter,
                "metadata": {
                    **adapter["metadata"],
                    "stop_signal_delivered": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "metadata",
        ),
        (
            {**adapter, "daemon_signal_shutdown_adapter_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "adapter id",
        ),
        (
            {**adapter, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_signal_shutdown_adapter(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as signal_exc:
        build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
            current_state=_execute_command()["runtime_state"],
            process_lock=_process_lock(),
            run_metadata=_run_metadata(),
            signal_name="SIGQUIT",
            received_at=RECEIVED_AT,
        )
    assert signal_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_signal_shutdown_adapter_invalid"
    )

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
    other_scheduler_run = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=other_scheduler_command,
        process_lock=other_scheduler_lock,
    )
    with pytest.raises(ArtifactHandoffError) as lock_scope_exc:
        build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
            current_state=other_scheduler_command["runtime_state"],
            process_lock=_process_lock(),
            run_metadata=_run_metadata(),
            received_at=RECEIVED_AT,
        )
    assert "lock scope" in lock_scope_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as run_scope_exc:
        build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
            current_state=_execute_command()["runtime_state"],
            process_lock=_process_lock(),
            run_metadata=other_scheduler_run,
            received_at=RECEIVED_AT,
        )
    assert "run scope" in run_scope_exc.value.detail

    other_same_scheduler_command = _execute_command()
    other_same_scheduler_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=other_same_scheduler_command,
        process_id=5252,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    with pytest.raises(ArtifactHandoffError) as process_lock_scope_exc:
        build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
            current_state=_execute_command()["runtime_state"],
            process_lock=other_same_scheduler_lock,
            run_metadata=_run_metadata(),
            received_at=RECEIVED_AT,
        )
    assert "process lock scope" in process_lock_scope_exc.value.detail

    execute_command = _execute_command()
    process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=execute_command,
        process_id=4242,
        host_id="ae-node-01",
        requested_at=CHECKED_AT,
    )
    run_metadata = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=execute_command,
        process_lock=process_lock,
    )
    forged_run_metadata = {
        **run_metadata,
        "daemon_cli_execute_command_id": "forged-command-id",
    }
    forged_run_metadata["daemon_run_id"] = daemon_cli._daemon_run_metadata_id(
        scheduler_id=forged_run_metadata["scheduler_id"],
        command_id=forged_run_metadata["daemon_cli_execute_command_id"],
        process_lock_id=forged_run_metadata["daemon_process_lock_id"],
        process=forged_run_metadata["process"],
        lifecycle=forged_run_metadata["lifecycle"],
    )
    with pytest.raises(ArtifactHandoffError) as command_scope_exc:
        build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
            current_state=execute_command["runtime_state"],
            process_lock=process_lock,
            run_metadata=forged_run_metadata,
            received_at=RECEIVED_AT,
        )
    assert "command scope" in command_scope_exc.value.detail
