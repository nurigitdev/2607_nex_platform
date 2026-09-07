from __future__ import annotations

import json

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
)
from test_nex_ae_artifacts import (
    auth_headers,
    build_client_with_artifact_store,
    sqlite_artifact_session_factory,
)


def test_scheduler_daemon_supervised_process_routes_persist_and_read_models() -> None:
    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
        sqlite_artifact_session_factory()
    )
    store.ensure_schema()
    client, _, _, _ = build_client_with_artifact_store(
        retention_scheduler_daemon_supervised_process_store=store
    )

    unauthorized_post = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        json={"action": "status_probe"},
    )
    dispatch_response = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        json={
            "action": "start_daemon",
            "enabled": True,
            "explicit_opt_in": True,
            "checked_at": "2026-09-08T02:10:00Z",
            "observed_at": "2026-09-08T02:10:04Z",
            "process_status": "RUNNING",
            "process_id": "6262",
            "host_id": "ae-node-route",
            "started_at": "2026-09-08T02:10:01Z",
            "requested_by": {
                "actor_type": "operator",
                "actor_id": "ag-retention-operator",
            },
            "reason": "supervised process API dispatch regression",
            "max_cycles": "2",
            "run_worker": True,
            "message": "process observed through protected route",
        },
        headers=auth_headers(),
    )
    dispatch_payload = dispatch_response.json()
    supervised_process_record = dispatch_payload["supervised_process_record"]
    record_id = supervised_process_record["daemon_supervised_process_record_id"]

    list_response = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        params={
            "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
            "action": "START_DAEMON",
            "process_status": "running",
            "limit": "1",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        (
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
            f"{record_id}"
        ),
        headers=auth_headers(),
    )
    unauthorized_list = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots"
    )
    invalid_action = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        params={"action": "restart"},
        headers=auth_headers(),
    )
    invalid_process_status = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        params={"process_status": "sleeping"},
        headers=auth_headers(),
    )
    invalid_limit = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        params={"limit": "0"},
        headers=auth_headers(),
    )
    missing_detail = client.get(
        (
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
            "missing"
        ),
        headers=auth_headers(),
    )
    list_payload = list_response.json()
    detail_payload = detail_response.json()
    serialized = json.dumps(
        {
            "dispatch": dispatch_payload,
            "list": list_payload,
            "detail": detail_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    assert unauthorized_post.status_code == 401
    assert dispatch_response.status_code == 200
    assert dispatch_payload["daemon_supervised_process_dispatch_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION
    )
    assert dispatch_payload["action"] == "start_daemon"
    assert dispatch_payload["process_status"] == "RUNNING"
    assert dispatch_payload["guardrails"]["process_control_allowed"] is False
    assert dispatch_payload["metadata"]["persistence_performed"] is True
    assert supervised_process_record["process_id"] == 6262
    assert supervised_process_record["process_running"] is True
    assert supervised_process_record["process_started_observed"] is True
    assert dispatch_payload["supervised_process_event"]["event_type"] == (
        "SUPERVISED_PROCESS_SNAPSHOT_RECORDED"
    )
    assert store.get_supervised_process_record(record_id) == supervised_process_record

    assert list_response.status_code == 200
    assert list_payload["daemon_supervised_process_collection_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION
    )
    assert list_payload["filter"] == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "action": "start_daemon",
        "process_status": "RUNNING",
    }
    assert list_payload["count"] == 1
    assert list_payload["items"][0]["daemon_supervised_process_record_id"] == record_id
    assert list_payload["items"][0]["metadata"]["safe_for_ag_projection"] is True
    assert list_payload["guardrails"]["read_only"] is True
    assert list_payload["guardrails"]["ag_direct_process_control_allowed"] is False

    assert detail_response.status_code == 200
    assert detail_payload["daemon_supervised_process_detail_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION
    )
    assert detail_payload["daemon_supervised_process_record_id"] == record_id
    assert detail_payload["supervised_process_event_count"] == 1
    assert detail_payload["metadata"]["event_types"] == [
        "SUPERVISED_PROCESS_SNAPSHOT_RECORDED"
    ]
    assert detail_payload["guardrails"]["process_control_allowed"] is False

    assert unauthorized_list.status_code == 401
    assert invalid_action.status_code == 422
    assert invalid_process_status.status_code == 422
    assert invalid_limit.status_code == 422
    assert missing_detail.status_code == 404
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


def test_scheduler_daemon_supervised_process_routes_require_store() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    list_response = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        headers=auth_headers(),
    )
    detail_response = client.get(
        (
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
            "missing"
        ),
        headers=auth_headers(),
    )
    dispatch_response = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
        json={"action": "status_probe"},
        headers=auth_headers(),
    )

    assert list_response.status_code == 503
    assert detail_response.status_code == 503
    assert dispatch_response.status_code == 503
    assert list_response.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_supervised_process_store_unavailable"
    )
    assert detail_response.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_supervised_process_store_unavailable"
    )
    assert dispatch_response.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_supervised_process_store_unavailable"
    )
