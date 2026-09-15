from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

import nex_ag.operator_review_dispatch_execution as dispatch_execution
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from nex_ag.operator_review_cases import (
    apply_operator_review_escalation_dispatch_action,
    build_operator_review_escalation_dispatch_plan,
    build_operator_review_escalation_record,
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from nex_ag.operator_review_dispatch_execution import (
    ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES,
    DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV,
    DISPATCH_EXECUTION_DAEMON_CONTROL_ADMISSION_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_CONTROL_REQUEST_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV,
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV,
    DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_BLOCKED,
    DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED,
    DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_DETAILS_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED,
    DISPATCH_EXECUTION_DAEMON_LOOP_POLICY_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_POLICY_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_PROCESS_METADATA_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_PROCESS_RUNTIME_STATE_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_PROVIDER_MODE_ENV,
    DISPATCH_EXECUTION_DAEMON_TICK_EVENT_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_TICK_LOG_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_TICK_PLAN_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DAEMON_TICK_RESULT_SCHEMA_VERSION,
    DISPATCH_EXECUTION_PROVIDER_CONFIG_SCHEMA_VERSION,
    DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE,
    DISPATCH_EXECUTION_PROVIDER_MODE_ENV,
    DISPATCH_EXTERNAL_INCIDENT_PROVIDER_REQUEST_SCHEMA_VERSION,
    DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV,
    DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV,
    DISPATCH_HTTP_BACKOFF_SECONDS_ENV,
    DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS_ENV,
    DISPATCH_HTTP_MAX_RETRIES_ENV,
    DISPATCH_HTTP_READ_TIMEOUT_SECONDS_ENV,
    DISPATCH_HTTP_TIMEOUT_SECONDS_ENV,
    DISPATCH_EXECUTION_PROVIDER_CATALOG_SCHEMA_VERSION,
    DISPATCH_EXECUTION_PROVIDER_MODE,
    DISPATCH_LIVE_PROVIDER_ENABLE_ENV,
    DISPATCH_LIVE_PROVIDER_PROFILE_ENV,
    DISPATCH_LIVE_HTTP_TRANSPORT_ENVELOPE_SCHEMA_VERSION,
    DISPATCH_LIVE_HTTP_TRANSPORT_REQUEST_PLAN_SCHEMA_VERSION,
    DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV,
    DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV,
    DISPATCH_NOTIFICATION_PROVIDER_REQUEST_SCHEMA_VERSION,
    DISPATCH_PROVIDER_HTTP_CLIENT_RESULT_SCHEMA_VERSION,
    DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION,
    MockDispatchProviderHttpTransport,
    MockExternalIncidentDispatchProvider,
    MockNotificationDispatchProvider,
    assert_dispatch_execution_result_redacted,
    build_dispatch_execution_daemon_policy,
    build_dispatch_execution_daemon_control_admission,
    build_dispatch_execution_daemon_control_request,
    build_dispatch_execution_daemon_loop_policy,
    build_dispatch_execution_daemon_lifecycle_event_details,
    build_dispatch_execution_daemon_process_metadata,
    build_dispatch_execution_daemon_process_runtime_state,
    build_dispatch_execution_daemon_tick_event,
    build_dispatch_execution_daemon_tick_log_entry,
    build_dispatch_execution_daemon_tick_plan,
    build_dispatch_execution_provider_catalog,
    build_dispatch_execution_provider_config,
    build_dispatch_live_http_transport_headers,
    build_dispatch_live_http_transport,
    build_dispatch_live_http_transport_envelope,
    build_dispatch_live_http_transport_request_plan,
    build_external_incident_dispatch_provider_request,
    build_notification_dispatch_provider_request,
    build_dispatch_execution_result,
    build_dispatch_execution_result_metadata,
    build_dispatch_execution_transition_plan,
    build_mock_dispatch_execution_provider,
    execute_dispatch_provider_http_request,
    execute_dispatch_with_live_http_transport,
    execute_dispatch_with_mock_provider,
    execute_dispatch_with_mock_external_incident_provider,
    execute_dispatch_with_mock_notification_provider,
    execute_dispatch_with_provider_router,
    emit_dispatch_execution_daemon_lifecycle_event,
    normalize_dispatch_execution_provider_mode,
    normalize_dispatch_execution_provider_profile,
    record_dispatch_execution_result_metadata,
    run_dispatch_execution_daemon_bounded_loop,
    run_dispatch_execution_daemon_tick_once,
    summarize_dispatch_execution_daemon_bounded_loop_result,
    run_dispatch_execution_worker_once,
    _build_dispatch_provider_http_client_result,
    _build_provider_adapter_execution_result,
    _persist_worker_result_metadata,
    _worker_candidate_dispatches,
)
from nex_ag.operator_reviews import OperatorReviewNoteError, sha256_text


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def sample_escalation_candidate(**overrides: Any) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "case_escalation_item_schema_version": (
            "ag_operator_review_case_escalation_item.v1"
        ),
        "candidate_id": "case-0713:attention",
        "case_id": "case-0713",
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_dispatch_execution",
            "target_id": "target-0713",
        },
        "case_status": "OPEN",
        "case_priority": "HIGH",
        "assignment_ref": {
            "assignee_type": "user",
            "assignee_id": "employee-0713",
            "tenant_id": "local-tenant",
        },
        "attention_status": "ATTENTION",
        "sla_state": "WARNING",
        "escalation_level": "ATTENTION",
        "elapsed_seconds": 7200,
        "warning_after_seconds": 3600,
        "overdue_after_seconds": 10800,
        "recommended_actions": ["notify_operator"],
        "reason_codes": ["sla_warning"],
        "runbook_ids": ["ag.operator_review_case.sla_followup.v1"],
        "observed_at": "2026-09-12T13:00:00Z",
    }
    candidate.update(overrides)
    return candidate


def sample_dispatch(**plan_overrides: Any) -> dict[str, Any]:
    escalation = build_operator_review_escalation_record(
        sample_escalation_candidate(**plan_overrides.pop("candidate_overrides", {})),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0713-escalation",
        created_at="2026-09-12T13:00:00Z",
    )
    plan = build_operator_review_escalation_dispatch_plan(
        escalation,
        plan_overrides or None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0713-dispatch",
        created_at="2026-09-12T13:05:00Z",
    )
    assert isinstance(plan["dispatch_record"], dict)
    return plan["dispatch_record"]


def sample_live_channel_dispatch(**overrides: Any) -> dict[str, Any]:
    safe_body = overrides.pop("safe_body", None)
    provider_fingerprint = overrides.pop("provider_payload_fingerprint", None)
    dispatch = {
        **sample_dispatch(),
        "channel_type": "EMAIL",
        "dispatch_intent": "NOTIFY_OWNER",
        "provider_profile": "email-notification-default",
        "safe_subject": "SLA warning",
        "safe_body_hash": None,
        "safe_body_preview": None,
        "provider_payload_hash": None,
    }
    dispatch.update(overrides)
    if safe_body is not None:
        dispatch["safe_body_hash"] = sha256_text(str(safe_body))
        dispatch["safe_body_preview"] = str(safe_body)
    if provider_fingerprint is not None:
        dispatch["provider_payload_hash"] = sha256_text(str(provider_fingerprint))
    return dispatch


def build_dispatch_service(
    *dispatches: dict[str, Any],
) -> tuple[OperatorReviewCaseService, OperatorReviewEscalationDispatchStore]:
    dispatch_store = OperatorReviewEscalationDispatchStore()
    for dispatch in dispatches:
        dispatch_store.save(dispatch)
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=dispatch_store,
    )
    return service, dispatch_store


def test_dispatch_execution_provider_catalog_is_mock_first_and_redacted() -> None:
    catalog = build_dispatch_execution_provider_catalog()

    assert catalog["provider_catalog_schema_version"] == (
        DISPATCH_EXECUTION_PROVIDER_CATALOG_SCHEMA_VERSION
    )
    assert catalog["provider_mode"] == DISPATCH_EXECUTION_PROVIDER_MODE
    assert catalog["default_provider_profile"] == DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE
    assert catalog["live_provider_execution"] is False
    assert catalog["outbound_network_delivery"] is False
    assert catalog["eligible_channel_types"] == ["MOCK"]
    assert catalog["profiles"]["mock-default"]["result_status"] == "SUCCEEDED"
    assert catalog["profiles"]["mock-failure"]["result_status"] == "FAILED"
    assert catalog["result_contract"]["schema_version"] == (
        DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION
    )
    assert catalog["result_contract"]["allowed_statuses"] == list(
        ALLOWED_DISPATCH_EXECUTION_RESULT_STATUSES
    )
    assert catalog["redaction"]["raw_provider_payload_included"] is False
    assert "provider_api_key" not in json.dumps(catalog)

    normalized = normalize_dispatch_execution_provider_profile(
        None,
        channel_type="MOCK",
    )
    assert normalized["profile_id"] == "mock-default"


def test_dispatch_execution_provider_config_defaults_are_safe() -> None:
    config = build_dispatch_execution_provider_config({})

    assert config["provider_config_schema_version"] == (
        DISPATCH_EXECUTION_PROVIDER_CONFIG_SCHEMA_VERSION
    )
    assert config["configured_provider_mode"] == "mock_first_only"
    assert config["effective_provider_mode"] == "mock_first_only"
    assert config["live_network_calls_enabled"] is False
    assert config["execution_provider_profile"] == "mock-default"
    assert config["live_provider_profile"] == "notification-webhook-default"
    assert config["http"] == {
        "timeout_seconds": 15.0,
        "connect_timeout_seconds": 5.0,
        "read_timeout_seconds": 15.0,
        "max_retries": 2,
        "backoff_seconds": 1.0,
    }
    assert config["endpoints"]["notification"]["configured"] is False
    assert config["endpoints"]["notification"]["endpoint_hint"] is None
    assert config["endpoints"]["external_incident"]["token_configured"] is False
    assert "external-incident-default" in config["profiles"]["live_readiness"]
    assert "provider_api_key" not in json.dumps(config)
    assert_dispatch_execution_result_redacted(config)


def test_dispatch_execution_provider_config_redacts_env_and_clamps() -> None:
    env = {
        DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "live_http",
        DISPATCH_LIVE_PROVIDER_ENABLE_ENV: "0",
        DISPATCH_LIVE_PROVIDER_PROFILE_ENV: "external-incident-default",
        DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: "https://notify.invalid/hook/secret",
        DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0722",
        DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV: "incident-secret-url",
        DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV: "incident-token-0722",
        DISPATCH_HTTP_TIMEOUT_SECONDS_ENV: "250",
        DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS_ENV: "0",
        DISPATCH_HTTP_READ_TIMEOUT_SECONDS_ENV: "not-a-number",
        DISPATCH_HTTP_MAX_RETRIES_ENV: "99",
        DISPATCH_HTTP_BACKOFF_SECONDS_ENV: "-1",
    }

    guarded = build_dispatch_execution_provider_config(env)

    assert guarded["configured_provider_mode"] == "live_http"
    assert guarded["effective_provider_mode"] == "mock_http"
    assert guarded["live_network_calls_enabled"] is False
    assert guarded["live_provider_profile"] == "external-incident-default"
    assert guarded["http"] == {
        "timeout_seconds": 120.0,
        "connect_timeout_seconds": 0.1,
        "read_timeout_seconds": 15.0,
        "max_retries": 5,
        "backoff_seconds": 0.0,
    }
    assert guarded["endpoints"]["notification"]["configured"] is True
    assert guarded["endpoints"]["notification"]["endpoint_hint"] == (
        "https://notify.invalid/<redacted>"
    )
    assert guarded["endpoints"]["notification"]["token_configured"] is True
    assert guarded["endpoints"]["external_incident"]["endpoint_hint"] == (
        "<configured-endpoint>"
    )
    serialized = json.dumps(guarded)
    assert "https://notify.invalid/hook/secret" not in serialized
    assert "notify-token-0722" not in serialized
    assert "incident-token-0722" not in serialized
    assert_dispatch_execution_result_redacted(guarded)

    enabled = build_dispatch_execution_provider_config(
        {**env, DISPATCH_LIVE_PROVIDER_ENABLE_ENV: "1"}
    )
    assert enabled["effective_provider_mode"] == "live_http"
    assert enabled["live_network_calls_enabled"] is True

    fallback_retries = build_dispatch_execution_provider_config(
        {DISPATCH_HTTP_MAX_RETRIES_ENV: "not-a-number"}
    )
    assert fallback_retries["http"]["max_retries"] == 2


def test_dispatch_execution_provider_config_rejects_unknown_mode() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc_info:
        normalize_dispatch_execution_provider_mode("sidecar")

    assert exc_info.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_provider_mode_unsupported"
    )


def test_dispatch_execution_daemon_policy_defaults_are_safe() -> None:
    policy = build_dispatch_execution_daemon_policy({})

    assert policy["daemon_policy_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_POLICY_SCHEMA_VERSION
    )
    assert policy["enabled"] is False
    assert policy["dry_run"] is True
    assert policy["batch_limit"] == 10
    assert policy["cycle_limit"] == 1
    assert policy["interval_seconds"] == 60
    assert policy["source_table"] == "ag_op_esc_dispatches"
    assert policy["configured_provider_mode"] == "mock_first_only"
    assert policy["effective_provider_mode"] == "mock_first_only"
    assert policy["live_network_calls_enabled"] is False
    assert policy["requires_confirm_tick"] is True
    assert policy["requires_protected_control"] is True
    assert policy["new_tables_required"] is False
    assert policy["env"]["live_provider_enable"] == DISPATCH_LIVE_PROVIDER_ENABLE_ENV
    assert_dispatch_execution_result_redacted(policy)


def test_dispatch_execution_daemon_policy_clamps_and_guards_live_http() -> None:
    env = {
        DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "yes",
        DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
        DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV: "999",
        DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV: "0",
        DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV: "99999",
        DISPATCH_EXECUTION_DAEMON_PROVIDER_MODE_ENV: "live_http",
        DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: "https://notify.invalid/hook/secret",
        DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0742",
    }

    guarded = build_dispatch_execution_daemon_policy(env)

    assert guarded["enabled"] is True
    assert guarded["dry_run"] is False
    assert guarded["batch_limit"] == 50
    assert guarded["cycle_limit"] == 1
    assert guarded["interval_seconds"] == 3600
    assert guarded["configured_provider_mode"] == "live_http"
    assert guarded["effective_provider_mode"] == "mock_http"
    assert guarded["live_network_calls_enabled"] is False
    serialized = json.dumps(guarded)
    assert "notify-token-0742" not in serialized
    assert "https://notify.invalid/hook/secret" not in serialized

    enabled = build_dispatch_execution_daemon_policy(
        {**env, DISPATCH_LIVE_PROVIDER_ENABLE_ENV: "1"}
    )
    assert enabled["effective_provider_mode"] == "live_http"
    assert enabled["live_network_calls_enabled"] is True


def test_dispatch_execution_daemon_policy_rejects_unknown_provider_mode() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc_info:
        build_dispatch_execution_daemon_policy(
            {DISPATCH_EXECUTION_DAEMON_PROVIDER_MODE_ENV: "socket"}
        )

    assert exc_info.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_provider_mode_unsupported"
    )


def test_dispatch_execution_daemon_loop_policy_is_bounded_and_redacted() -> None:
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
            DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV: "2",
            DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV: "20",
            DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV: "0",
            DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0772",
        }
    )

    loop_policy = build_dispatch_execution_daemon_loop_policy(policy=policy)

    assert loop_policy["daemon_loop_policy_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_LOOP_POLICY_SCHEMA_VERSION
    )
    assert loop_policy["loop_mode"] == "bounded"
    assert loop_policy["enabled"] is True
    assert loop_policy["dry_run"] is False
    assert loop_policy["batch_limit"] == 2
    assert loop_policy["cycle_limit"] == 10
    assert loop_policy["interval_seconds"] == 1
    assert loop_policy["tick_executor"] == "run_dispatch_execution_daemon_tick_once"
    assert loop_policy["continuous_loop_started"] is False
    assert loop_policy["subprocess_started"] is False
    assert loop_policy["new_tables_required"] is False
    assert loop_policy["guardrails"] == {
        "finite_cycle_limit": True,
        "confirm_tick_required": True,
        "default_dry_run": True,
        "sleep_is_injected": True,
        "raw_payloads_allowed": False,
        "provider_secrets_allowed": False,
    }
    assert "notify-token-0772" not in json.dumps(loop_policy)
    assert_dispatch_execution_result_redacted(loop_policy)


def test_dispatch_execution_daemon_bounded_loop_skips_disabled() -> None:
    service, _dispatch_store = build_dispatch_service(sample_dispatch())

    result = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        started_at="2026-09-15T09:00:00Z",
    )

    assert result["daemon_bounded_loop_result_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION
    )
    assert result["loop_status"] == "SKIPPED"
    assert result["stop_reason"] == "daemon_disabled"
    assert result["cycle_count"] == 0
    assert result["tick_results"] == []
    assert result["summary"]["tick_count"] == 0
    assert result["new_tables_required"] is False
    assert summarize_dispatch_execution_daemon_bounded_loop_result(result) == {
        "loop_status": "SKIPPED",
        "stop_reason": "daemon_disabled",
        "worker_id": "ag-dispatch-execution-daemon",
        "cycle_count": 0,
        "cycle_limit": 1,
        "processed_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "retry_wait_count": 0,
        "new_tables_required": False,
        "redaction": result["redaction"],
    }
    assert_dispatch_execution_result_redacted(result)


def test_dispatch_execution_daemon_bounded_loop_blocks_without_confirm() -> None:
    service, dispatch_store = build_dispatch_service(sample_dispatch())
    policy = build_dispatch_execution_daemon_policy(
        {DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"}
    )

    result = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=policy,
        started_at="2026-09-15T09:01:00Z",
    )

    assert result["loop_status"] == "BLOCKED"
    assert result["stop_reason"] == "confirm_tick_required"
    assert result["cycle_count"] == 1
    assert result["summary"]["blocked_count"] == 1
    assert result["tick_results"][0]["blocked_reason"] == "confirm_tick_required"
    assert dispatch_store.list_dispatches(limit=10)[0]["dispatch_status"] == "PENDING"


def test_dispatch_execution_daemon_bounded_loop_runs_until_cycle_limit() -> None:
    first = sample_dispatch(
        candidate_overrides={"candidate_id": "case-0772:first", "case_id": "case-0772-a"}
    )
    second = sample_dispatch(
        candidate_overrides={"candidate_id": "case-0772:second", "case_id": "case-0772-b"}
    )
    second["dispatch_id"] = "dispatch-0772-second"
    service, dispatch_store = build_dispatch_service(first, second)
    sleep_calls: list[int] = []
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
            DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV: "2",
            DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV: "3",
        }
    )

    result = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=policy,
        confirm_tick=True,
        dry_run=False,
        started_at="2026-09-15T09:02:00Z",
        sleep_fn=sleep_calls.append,
    )
    summary = summarize_dispatch_execution_daemon_bounded_loop_result(result)

    assert result["loop_status"] == "COMPLETED"
    assert result["stop_reason"] == "cycle_limit_reached"
    assert result["cycle_count"] == 2
    assert result["summary"]["processed_count"] == 2
    assert result["summary"]["succeeded_count"] == 2
    assert result["tick_results"][0]["executed_at"] == "2026-09-15T09:02:00Z"
    assert result["tick_results"][1]["executed_at"] == "2026-09-15T09:02:03Z"
    assert sleep_calls == [3]
    assert dispatch_store.get(first["dispatch_id"])["dispatch_status"] == "SUCCEEDED"
    assert dispatch_store.get("dispatch-0772-second")["dispatch_status"] == "SUCCEEDED"
    assert summary["processed_count"] == 2
    assert summary["new_tables_required"] is False
    assert_dispatch_execution_result_redacted(result)


def test_dispatch_execution_daemon_bounded_loop_stops_when_idle() -> None:
    service, _dispatch_store = build_dispatch_service()
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV: "3",
        }
    )

    result = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        policy=policy,
        confirm_tick=True,
        started_at="2026-09-15T09:03:00Z",
    )

    assert result["loop_status"] == "IDLE"
    assert result["stop_reason"] == "idle"
    assert result["cycle_count"] == 1
    assert result["summary"]["candidate_count"] == 0
    assert result["summary"]["by_tick_status"] == {"COMPLETED": 1}


def test_dispatch_execution_daemon_bounded_loop_helper_edges() -> None:
    assert dispatch_execution._dispatch_daemon_bounded_loop_status([], "idle") == "IDLE"
    assert (
        dispatch_execution._dispatch_daemon_bounded_loop_status(
            [{"candidate_count": 1}],
            "idle",
        )
        == "COMPLETED"
    )
    assert (
        dispatch_execution._bounded_int_value(
            "not-a-number",
            default=7,
            minimum=1,
            maximum=10,
        )
        == 7
    )


def test_dispatch_execution_daemon_process_metadata_defaults_are_disabled() -> None:
    metadata = build_dispatch_execution_daemon_process_metadata(
        started_at="2026-09-15T10:00:00Z"
    )

    assert metadata["daemon_process_metadata_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_PROCESS_METADATA_SCHEMA_VERSION
    )
    assert metadata["process_status"] == "DISABLED"
    assert metadata["process_id"] is None
    assert metadata["process_id_present"] is False
    assert metadata["entrypoint"] == "python -m nex_ag.operator_review_dispatch_daemon"
    assert metadata["loop_mode"] == "bounded"
    assert metadata["lifecycle_event_source"] == "service_operational_events"
    assert metadata["liveness_source"] == "service_worker_heartbeats"
    assert metadata["new_tables_required"] is False
    assert "postgresql://" not in json.dumps(metadata)
    assert_dispatch_execution_result_redacted(metadata)


def test_dispatch_execution_daemon_process_metadata_clamps_and_marks_ready() -> None:
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV: "3",
        }
    )
    loop_policy = build_dispatch_execution_daemon_loop_policy(policy=policy)

    metadata = build_dispatch_execution_daemon_process_metadata(
        process_id=9_999_999_999,
        process_run_id="process-run-0773",
        worker_id="ag-dispatch-daemon-0773",
        entrypoint="python -m nex_ag.operator_review_dispatch_daemon --once",
        policy=policy,
        loop_policy=loop_policy,
        started_at="2026-09-15T10:01:00Z",
    )

    assert metadata["process_run_id"] == "process-run-0773"
    assert metadata["worker_id"] == "ag-dispatch-daemon-0773"
    assert metadata["process_id"] == 2_147_483_647
    assert metadata["process_id_present"] is True
    assert metadata["process_status"] == "READY"
    assert metadata["cycle_limit"] == 3
    assert metadata["enabled"] is True


def test_dispatch_execution_daemon_process_runtime_state_tracks_loop_results() -> None:
    service, _dispatch_store = build_dispatch_service(sample_dispatch())
    policy = build_dispatch_execution_daemon_policy(
        {DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"}
    )
    metadata = build_dispatch_execution_daemon_process_metadata(
        policy=policy,
        started_at="2026-09-15T10:02:00Z",
    )
    ready_state = build_dispatch_execution_daemon_process_runtime_state(
        metadata,
        observed_at="2026-09-15T10:02:01Z",
    )

    assert ready_state["daemon_process_runtime_state_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_PROCESS_RUNTIME_STATE_SCHEMA_VERSION
    )
    assert ready_state["state_status"] == "READY"
    assert ready_state["loop_summary"] is None
    assert ready_state["control_family"].endswith("/dispatch-daemon/controls")

    blocked_loop = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        policy=policy,
        started_at="2026-09-15T10:03:00Z",
    )
    blocked_state = build_dispatch_execution_daemon_process_runtime_state(
        metadata,
        loop_result=blocked_loop,
        observed_at="2026-09-15T10:03:01Z",
    )

    assert blocked_state["state_status"] == "DEGRADED"
    assert blocked_state["loop_summary"]["loop_status"] == "BLOCKED"
    assert blocked_state["loop_summary"]["stop_reason"] == "confirm_tick_required"
    assert blocked_state["new_tables_required"] is False
    assert_dispatch_execution_result_redacted(blocked_state)


def test_dispatch_execution_daemon_process_runtime_state_terminal_statuses() -> None:
    disabled = build_dispatch_execution_daemon_process_metadata(
        started_at="2026-09-15T10:04:00Z"
    )
    disabled_state = build_dispatch_execution_daemon_process_runtime_state(disabled)
    assert disabled_state["state_status"] == "DISABLED"

    enabled_policy = build_dispatch_execution_daemon_policy(
        {DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"}
    )
    metadata = build_dispatch_execution_daemon_process_metadata(policy=enabled_policy)
    completed_state = build_dispatch_execution_daemon_process_runtime_state(
        metadata,
        loop_result={
            "loop_status": "COMPLETED",
            "stop_reason": "cycle_limit_reached",
            "worker_id": "worker",
            "cycle_count": 1,
            "cycle_limit": 1,
            "summary": {
                "processed_count": 1,
                "succeeded_count": 1,
                "failed_count": 0,
                "retry_wait_count": 0,
            },
            "new_tables_required": False,
        },
    )
    unknown_state = dispatch_execution._dispatch_daemon_process_runtime_state_status(
        {"process_status": "READY"},
        {"loop_status": "RUNNING"},
    )

    assert completed_state["state_status"] == "STOPPED"
    assert unknown_state == "UNKNOWN"
    assert dispatch_execution._bounded_optional_process_id("bad") is None
    assert (
        dispatch_execution._dispatch_daemon_process_metadata_status(
            {"enabled": True, "subprocess_started": True}
        )
        == "RUNNING"
    )


def test_dispatch_execution_daemon_lifecycle_details_are_safe() -> None:
    metadata = build_dispatch_execution_daemon_process_metadata(
        process_run_id="process-run-0775",
        worker_id="worker-0775",
        started_at="2026-09-15T12:00:00Z",
    )
    details = build_dispatch_execution_daemon_lifecycle_event_details(metadata)

    assert details["daemon_lifecycle_event_details_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_DETAILS_SCHEMA_VERSION
    )
    assert details["process_run_id"] == "process-run-0775"
    assert details["worker_id"] == "worker-0775"
    assert details["cycle_count"] == 0
    assert details["processed_count"] == 0
    assert details["lifecycle_event_source"] == "service_operational_events"
    assert details["new_tables_required"] is False
    assert details["raw_provider_payload_included"] is False
    assert_dispatch_execution_result_redacted(details)


def test_dispatch_execution_daemon_lifecycle_emit_started() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    metadata = build_dispatch_execution_daemon_process_metadata(
        process_run_id="process-run-0775-started",
        worker_id="worker-0775",
        started_at="2026-09-15T12:01:00Z",
    )

    result = emit_dispatch_execution_daemon_lifecycle_event(
        emitter,
        process_metadata=metadata,
        event_name="started",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        occurred_at="2026-09-15T12:01:01Z",
    )

    assert result.ok is True
    assert result.event is not None
    assert result.event["event_type"] == DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED
    assert result.event["severity"] == "INFO"
    assert result.event["subject_ref"] == {
        "type": "operator_review_dispatch_daemon_process",
        "id": "process-run-0775-started",
    }
    assert event_store.get_event(result.event["event_id"]) is not None


def test_dispatch_execution_daemon_lifecycle_emit_completed_and_blocked() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    service, _dispatch_store = build_dispatch_service()
    policy = build_dispatch_execution_daemon_policy(
        {DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"}
    )
    metadata = build_dispatch_execution_daemon_process_metadata(
        policy=policy,
        process_run_id="process-run-0775-completed",
        started_at="2026-09-15T12:02:00Z",
    )
    idle_loop = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        policy=policy,
        confirm_tick=True,
        started_at="2026-09-15T12:02:01Z",
    )
    idle_state = build_dispatch_execution_daemon_process_runtime_state(
        metadata,
        loop_result=idle_loop,
        observed_at="2026-09-15T12:02:02Z",
    )
    completed = emit_dispatch_execution_daemon_lifecycle_event(
        emitter,
        process_metadata=metadata,
        event_name="completed",
        loop_result=idle_loop,
        runtime_state=idle_state,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        occurred_at="2026-09-15T12:02:03Z",
    )

    assert completed.ok is True
    assert completed.event is not None
    assert completed.event["event_type"] == (
        DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED
    )
    assert completed.event["details"]["loop_status"] == "IDLE"

    blocked_loop = run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=REQUEST_ID,
        policy=policy,
        confirm_tick=False,
        started_at="2026-09-15T12:03:00Z",
    )
    blocked_state = build_dispatch_execution_daemon_process_runtime_state(
        metadata,
        loop_result=blocked_loop,
    )
    blocked = emit_dispatch_execution_daemon_lifecycle_event(
        emitter,
        process_metadata=metadata,
        event_name="completed",
        loop_result=blocked_loop,
        runtime_state=blocked_state,
    )

    assert blocked.ok is True
    assert blocked.event is not None
    assert blocked.event["event_type"] == DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_BLOCKED
    assert blocked.event["severity"] == "WARNING"
    assert blocked.event["details"]["stop_reason"] == "confirm_tick_required"


def test_dispatch_execution_daemon_lifecycle_emit_reports_missing_emitter() -> None:
    metadata = build_dispatch_execution_daemon_process_metadata(
        process_run_id="process-run-0775-missing",
        started_at="2026-09-15T12:04:00Z",
    )

    result = emit_dispatch_execution_daemon_lifecycle_event(
        None,
        process_metadata=metadata,
        event_name="started",
    )

    assert result.ok is False
    assert result.status_code == 503
    assert result.error_code == (
        "ag.operator_review_escalation_dispatch_daemon_lifecycle_"
        "emitter_not_configured"
    )


def test_dispatch_execution_daemon_tick_plan_defaults_to_disabled_idle() -> None:
    service, _dispatch_store = build_dispatch_service()

    plan = build_dispatch_execution_daemon_tick_plan(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at="2026-09-14T11:43:00Z",
    )

    assert plan["daemon_tick_plan_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_TICK_PLAN_SCHEMA_VERSION
    )
    assert plan["plan_status"] == "DISABLED"
    assert plan["candidate_count"] == 0
    assert plan["candidate_dispatch_ids"] == []
    assert plan["candidate_status_counts"] == {}
    assert plan["dry_run"] is True
    assert plan["requires_confirm_tick"] is True
    assert plan["will_mutate_without_confirm"] is False
    assert plan["new_tables_required"] is False
    assert_dispatch_execution_result_redacted(plan)

    enabled_idle = build_dispatch_execution_daemon_tick_plan(
        service,
        request_id=REQUEST_ID,
        policy=build_dispatch_execution_daemon_policy(
            {DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"}
        ),
        planned_at="2026-09-14T11:43:10Z",
    )
    assert enabled_idle["plan_status"] == "IDLE"
    assert enabled_idle["candidate_count"] == 0


def test_dispatch_execution_daemon_tick_plan_summarizes_candidates_without_mutation() -> None:
    pending = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0743:pending",
            "case_id": "case-0743-pending",
        }
    )
    retry_wait = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0743:retry",
            "case_id": "case-0743-retry",
        }
    )
    retry_wait.update(
        {
            "dispatch_id": "dispatch-0743-retry",
            "dispatch_status": "RETRY_WAIT",
            "attempt_count": 1,
            "last_error_code": "provider_timeout",
            "next_attempt_at": "2026-09-14T12:00:00Z",
        }
    )
    failed = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0743:failed",
            "case_id": "case-0743-failed",
        }
    )
    failed.update(
        {
            "dispatch_id": "dispatch-0743-failed",
            "dispatch_status": "FAILED",
            "attempt_count": 3,
        }
    )
    service, dispatch_store = build_dispatch_service(pending, retry_wait, failed)
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "false",
            DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV: "2",
        }
    )

    plan = build_dispatch_execution_daemon_tick_plan(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=policy,
        planned_at="2026-09-14T11:44:00Z",
    )

    assert plan["plan_status"] == "READY"
    assert plan["candidate_count"] == 2
    assert plan["candidate_dispatch_ids"] == [
        pending["dispatch_id"],
        "dispatch-0743-retry",
    ]
    assert plan["candidate_status_counts"] == {"PENDING": 1, "RETRY_WAIT": 1}
    assert plan["candidate_channel_counts"] == {"MOCK": 2}
    assert plan["dry_run"] is False
    assert plan["candidate_summaries"][1]["attempt_count"] == 1
    assert plan["candidate_summaries"][1]["last_error_code"] == "provider_timeout"
    assert dispatch_store.get(pending["dispatch_id"])["dispatch_status"] == "PENDING"
    assert dispatch_store.get("dispatch-0743-retry")["dispatch_status"] == "RETRY_WAIT"
    serialized = json.dumps(plan)
    assert "idem-0713" not in serialized
    assert "provider_timeout" in serialized
    assert_dispatch_execution_result_redacted(plan)


def test_dispatch_execution_daemon_tick_once_blocks_disabled_and_unconfirmed() -> None:
    dispatch = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0744:block",
            "case_id": "case-0744-block",
        }
    )
    service, dispatch_store = build_dispatch_service(dispatch)

    disabled = run_dispatch_execution_daemon_tick_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        executed_at="2026-09-14T11:50:00Z",
    )

    assert disabled["daemon_tick_result_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_TICK_RESULT_SCHEMA_VERSION
    )
    assert disabled["tick_status"] == "BLOCKED"
    assert disabled["blocked_reason"] == "daemon_disabled"
    assert disabled["worker_run"] is None
    assert disabled["candidate_count"] == 1
    assert dispatch_store.get(dispatch["dispatch_id"])["dispatch_status"] == "PENDING"

    enabled_policy = build_dispatch_execution_daemon_policy(
        {DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1"}
    )
    unconfirmed = run_dispatch_execution_daemon_tick_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=enabled_policy,
        executed_at="2026-09-14T11:51:00Z",
    )

    assert unconfirmed["tick_status"] == "BLOCKED"
    assert unconfirmed["blocked_reason"] == "confirm_tick_required"
    assert unconfirmed["worker_run"] is None
    assert dispatch_store.get(dispatch["dispatch_id"])["dispatch_status"] == "PENDING"
    assert_dispatch_execution_result_redacted(unconfirmed)


def test_dispatch_execution_daemon_tick_once_runs_dry_run_and_confirmed_mutation() -> None:
    dry_dispatch = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0744:dry",
            "case_id": "case-0744-dry",
        }
    )
    dry_service, dry_store = build_dispatch_service(dry_dispatch)
    dry_policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_BATCH_LIMIT_ENV: "1",
        }
    )

    dry_result = run_dispatch_execution_daemon_tick_once(
        dry_service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=dry_policy,
        confirm_tick=True,
        executed_at="2026-09-14T11:52:00Z",
    )

    assert dry_result["tick_status"] == "COMPLETED"
    assert dry_result["dry_run"] is True
    assert dry_result["worker_run"]["dry_run"] is True
    assert dry_result["processed_count"] == 1
    assert dry_result["succeeded_count"] == 0
    assert dry_store.get(dry_dispatch["dispatch_id"])["dispatch_status"] == "PENDING"

    live_dispatch = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0744:run",
            "case_id": "case-0744-run",
        }
    )
    live_service, live_store = build_dispatch_service(live_dispatch)
    live_policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
        }
    )

    completed = run_dispatch_execution_daemon_tick_once(
        live_service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=live_policy,
        confirm_tick=True,
        dry_run=False,
        executed_at="2026-09-14T11:53:00Z",
    )

    assert completed["tick_status"] == "COMPLETED"
    assert completed["worker_run"]["run_status"] == "COMPLETED"
    assert completed["processed_count"] == 1
    assert completed["succeeded_count"] == 1
    assert live_store.get(live_dispatch["dispatch_id"])["dispatch_status"] == "SUCCEEDED"
    assert live_store.get(live_dispatch["dispatch_id"])["metadata"][
        "last_execution_result"
    ]["execution_status"] == "SUCCEEDED"
    assert_dispatch_execution_result_redacted(completed)


def test_dispatch_execution_daemon_tick_event_and_log_project_safe_success() -> None:
    dispatch = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0745:success",
            "case_id": "case-0745-success",
        }
    )
    service, _dispatch_store = build_dispatch_service(dispatch)
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
        }
    )
    tick = run_dispatch_execution_daemon_tick_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=policy,
        confirm_tick=True,
        executed_at="2026-09-14T12:45:00Z",
    )

    event = build_dispatch_execution_daemon_tick_event(tick)
    log_entry = build_dispatch_execution_daemon_tick_log_entry(tick)

    assert event["daemon_tick_event_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_TICK_EVENT_SCHEMA_VERSION
    )
    assert event["event_type"].endswith(".completed")
    assert event["severity"] == "INFO"
    assert event["summary"]["processed_count"] == 1
    assert event["summary"]["new_tables_required"] is False
    assert log_entry["daemon_tick_log_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_TICK_LOG_SCHEMA_VERSION
    )
    assert log_entry["severity"] == "INFO"
    assert "processed=1" in log_entry["message"]
    serialized = json.dumps({"event": event, "log": log_entry})
    assert "provider_result_ref" not in serialized
    assert "actions" not in serialized
    assert_dispatch_execution_result_redacted(event)
    assert_dispatch_execution_result_redacted(log_entry)


def test_dispatch_execution_daemon_tick_event_and_log_project_warnings_and_errors() -> None:
    blocked_dispatch = sample_dispatch(
        candidate_overrides={
            "candidate_id": "case-0745:block",
            "case_id": "case-0745-block",
        }
    )
    blocked_service, _blocked_store = build_dispatch_service(blocked_dispatch)
    blocked_tick = run_dispatch_execution_daemon_tick_once(
        blocked_service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        executed_at="2026-09-14T12:46:00Z",
    )
    blocked_event = build_dispatch_execution_daemon_tick_event(
        blocked_tick,
        event_id="event-0745-blocked",
        occurred_at="2026-09-14T12:46:01Z",
    )

    assert blocked_event["severity"] == "WARNING"
    assert blocked_event["summary"]["blocked_reason"] == "daemon_disabled"
    assert blocked_event["event_id"] == "event-0745-blocked"

    failed_dispatch = sample_dispatch(
        provider_profile="mock-failure",
        candidate_overrides={
            "candidate_id": "case-0745:failed",
            "case_id": "case-0745-failed",
        },
    )
    failed_dispatch["attempt_count"] = 2
    failed_service, _failed_store = build_dispatch_service(failed_dispatch)
    policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
        }
    )
    failed_tick = run_dispatch_execution_daemon_tick_once(
        failed_service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=policy,
        provider_profile="mock-failure",
        confirm_tick=True,
        executed_at="2026-09-14T12:47:00Z",
    )
    failed_log = build_dispatch_execution_daemon_tick_log_entry(
        failed_tick,
        log_id="log-0745-failed",
        emitted_at="2026-09-14T12:47:01Z",
    )

    assert failed_tick["failed_count"] == 1
    assert failed_log["severity"] == "ERROR"
    assert failed_log["log_id"] == "log-0745-failed"
    assert "failed=1" in failed_log["message"]

    retry_tick = {**failed_tick, "failed_count": 0, "retry_wait_count": 1}
    retry_event = build_dispatch_execution_daemon_tick_event(retry_tick)
    assert retry_event["severity"] == "WARNING"
    assert retry_event["summary"]["retry_wait_count"] == 1


def test_dispatch_execution_daemon_control_request_and_plan_admission_are_safe() -> None:
    control_request = build_dispatch_execution_daemon_control_request(
        {
            "action": "tick_plan",
            "dry_run": "0",
            "batch_limit": 999,
            "provider_mode": "mock_http",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0747",
                "authorization": "Bearer secret",
            },
            "reason_codes": ["operator_check", "", None],
            "provider_payload": {"secret": "nuri1004"},
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at="2026-09-14T13:47:00Z",
    )
    admission = build_dispatch_execution_daemon_control_admission(control_request)

    assert control_request["daemon_control_request_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_CONTROL_REQUEST_SCHEMA_VERSION
    )
    assert control_request["action"] == "tick_plan"
    assert control_request["dry_run"] is False
    assert control_request["batch_limit"] == 50
    assert control_request["operator_ref"] == {
        "operator_type": "user",
        "operator_id": "employee-0747",
    }
    assert control_request["reason_codes"] == ["operator_check"]
    assert control_request["control_request_hash"]
    assert admission["daemon_control_admission_schema_version"] == (
        DISPATCH_EXECUTION_DAEMON_CONTROL_ADMISSION_SCHEMA_VERSION
    )
    assert admission["admission_status"] == "ACCEPTED"
    assert admission["rejection_reason"] is None
    serialized = json.dumps({"request": control_request, "admission": admission})
    assert "Bearer secret" not in serialized
    assert "nuri1004" not in serialized
    assert '"provider_payload":' not in serialized
    assert_dispatch_execution_result_redacted(control_request)
    assert_dispatch_execution_result_redacted(admission)

    incomplete_operator = build_dispatch_execution_daemon_control_request(
        {"operator_ref": {"operator_type": "user"}},
        request_id=REQUEST_ID,
    )
    assert incomplete_operator["operator_ref"] is None


def test_dispatch_execution_daemon_control_tick_once_requires_enable_and_confirm() -> None:
    tick_once = build_dispatch_execution_daemon_control_request(
        {"action": "tick_once", "confirm_tick": False},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at="2026-09-14T13:48:00Z",
    )

    disabled = build_dispatch_execution_daemon_control_admission(tick_once)

    assert disabled["admission_status"] == "REJECTED"
    assert disabled["rejection_reason"] == "daemon_disabled"

    enabled_policy = build_dispatch_execution_daemon_policy(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "0",
        }
    )
    unconfirmed = build_dispatch_execution_daemon_control_admission(
        tick_once,
        policy=enabled_policy,
    )
    assert unconfirmed["admission_status"] == "REJECTED"
    assert unconfirmed["rejection_reason"] == "confirm_tick_required"

    confirmed_request = build_dispatch_execution_daemon_control_request(
        {
            "action": "tick_once",
            "confirm_tick": "yes",
            "dry_run": False,
            "provider_mode": "mock_first_only",
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at="2026-09-14T13:49:00Z",
    )
    accepted = build_dispatch_execution_daemon_control_admission(
        confirmed_request,
        policy=enabled_policy,
    )

    assert accepted["admission_status"] == "ACCEPTED"
    assert accepted["rejection_reason"] is None
    assert accepted["confirm_tick"] is True
    assert accepted["dry_run"] is False
    assert accepted["effective_provider_mode"] == "mock_first_only"


def test_dispatch_execution_daemon_control_rejects_unsupported_action_or_mode() -> None:
    with pytest.raises(OperatorReviewNoteError) as action_exc:
        build_dispatch_execution_daemon_control_request(
            {"action": "start_loop"},
            request_id=REQUEST_ID,
        )
    assert action_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_daemon_control_action_unsupported"
    )

    with pytest.raises(OperatorReviewNoteError) as mode_exc:
        build_dispatch_execution_daemon_control_request(
            {"action": "tick_plan", "provider_mode": "socket"},
            request_id=REQUEST_ID,
        )
    assert mode_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_provider_mode_unsupported"
    )

    with pytest.raises(OperatorReviewNoteError) as admission_exc:
        build_dispatch_execution_daemon_control_admission({"action": "stop_loop"})
    assert admission_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_daemon_control_action_unsupported"
    )


def test_dispatch_execution_provider_profile_rejects_unknown_or_live_channel() -> None:
    with pytest.raises(OperatorReviewNoteError) as unknown_exc:
        normalize_dispatch_execution_provider_profile(
            "live-provider",
            channel_type="MOCK",
        )
    assert unknown_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_provider_profile_unsupported"
    )

    with pytest.raises(OperatorReviewNoteError) as channel_exc:
        normalize_dispatch_execution_provider_profile(
            "mock-default",
            channel_type="EMAIL",
        )
    assert channel_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_provider_channel_deferred"
    )


def test_dispatch_execution_result_success_shape_is_safe() -> None:
    dispatch = sample_dispatch()

    result = build_dispatch_execution_result(
        dispatch,
        provider_result_ref="mock-result-0713",
        safe_result_message="Mock execution completed for the operator dispatch.",
        executed_at="2026-09-12T13:10:00Z",
    )

    assert result["execution_result_schema_version"] == (
        DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION
    )
    assert result["dispatch_id"] == dispatch["dispatch_id"]
    assert result["dispatch_status_before"] == "PENDING"
    assert result["execution_status"] == "SUCCEEDED"
    assert result["recommended_action"] == "SUCCEED"
    assert result["provider_profile"] == "mock-default"
    assert result["provider_result_ref"]["provider_result_hash"] == sha256_text(
        "mock-result-0713"
    )
    assert result["provider_result_hash"]
    assert result["safe_result_preview"] == (
        "Mock execution completed for the operator dispatch."
    )
    assert result["last_error_code"] is None
    assert result["redaction"]["idempotency_keys_included"] is False
    assert_dispatch_execution_result_redacted(result)


def test_dispatch_execution_result_failed_and_retry_validation() -> None:
    dispatch = sample_dispatch(provider_profile="mock-failure")

    with pytest.raises(OperatorReviewNoteError) as missing_error_exc:
        build_dispatch_execution_result(
            dispatch,
            execution_status="FAILED",
            provider_profile="mock-failure",
        )
    assert missing_error_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_error_code_required"
    )

    failed = build_dispatch_execution_result(
        dispatch,
        execution_status="FAILED",
        provider_profile="mock-failure",
        last_error_code="mock_dispatch_failed",
        safe_result_message="Mock provider returned a safe failure summary.",
        executed_at="2026-09-12T13:11:00Z",
    )
    assert failed["recommended_action"] == "FAIL"
    assert failed["last_error_code"] == "mock_dispatch_failed"
    assert failed["safe_result_preview"] == (
        "Mock provider returned a safe failure summary."
    )

    with pytest.raises(OperatorReviewNoteError) as missing_retry_exc:
        build_dispatch_execution_result(
            dispatch,
            execution_status="RETRY_WAIT",
            provider_profile="mock-failure",
        )
    assert missing_retry_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_retry_at_required"
    )

    retry = build_dispatch_execution_result(
        dispatch,
        execution_status="RETRY_WAIT",
        provider_profile="mock-failure",
        next_attempt_at="2026-09-12T13:30:00Z",
    )
    assert retry["recommended_action"] == "RETRY"
    assert retry["next_attempt_at"] == "2026-09-12T13:30:00Z"


def test_dispatch_execution_result_rejects_unsupported_status_and_sensitive_payloads() -> None:
    dispatch = sample_dispatch()

    with pytest.raises(OperatorReviewNoteError) as status_exc:
        build_dispatch_execution_result(dispatch, execution_status="DELIVERED")
    assert status_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_status_unsupported"
    )

    with pytest.raises(OperatorReviewNoteError) as key_exc:
        assert_dispatch_execution_result_redacted(
            {"provider_result": {"raw_provider_payload": {"secret": "nope"}}}
        )
    assert key_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_result_leak"
    )

    with pytest.raises(OperatorReviewNoteError) as flag_exc:
        assert_dispatch_execution_result_redacted(
            {"redaction": {"provider_secrets_included": True}}
        )
    assert flag_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_redaction_flag_leak"
    )

    with pytest.raises(OperatorReviewNoteError) as value_exc:
        assert_dispatch_execution_result_redacted(
            {
                "safe": {
                    "text": (
                        "postgresql+psycopg://nex_ag_user:secret@127.0.0.1/db"
                    )
                }
            }
        )
    assert value_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_sensitive_value_leak"
    )

    with pytest.raises(OperatorReviewNoteError) as list_key_exc:
        assert_dispatch_execution_result_redacted(
            [{"safe": "ok"}, {"raw_notification_payload": "nope"}]
        )
    assert list_key_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_result_leak"
    )

    with pytest.raises(OperatorReviewNoteError) as list_flag_exc:
        assert_dispatch_execution_result_redacted(
            [{"redaction": {"raw_prompt_included": True}}]
        )
    assert list_flag_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_redaction_flag_leak"
    )


def test_mock_dispatch_execution_provider_returns_safe_success_and_failure() -> None:
    dispatch = sample_dispatch()
    provider = build_mock_dispatch_execution_provider()

    result = provider.execute(dispatch, executed_at="2026-09-12T14:00:00Z")

    assert result["execution_status"] == "SUCCEEDED"
    assert result["recommended_action"] == "SUCCEED"
    assert result["provider_profile"] == "mock-default"
    assert result["safe_result_preview"] == "Mock dispatch delivered."
    assert result["executed_at"] == "2026-09-12T14:00:00Z"
    assert "mock-dispatch-execution" not in result["safe_result_preview"]
    assert result["redaction"]["raw_provider_payload_included"] is False

    failed = execute_dispatch_with_mock_provider(
        sample_dispatch(provider_profile="mock-failure"),
        profile_id="mock-failure",
        executed_at="2026-09-12T14:01:00Z",
    )

    assert failed["execution_status"] == "FAILED"
    assert failed["recommended_action"] == "FAIL"
    assert failed["last_error_code"] == "mock_dispatch_failed"
    assert failed["provider_result_ref"]["provider_result_hash"]


def test_mock_dispatch_execution_provider_skips_deferred_live_channel() -> None:
    dispatch = {
        **sample_dispatch(),
        "channel_type": "EMAIL",
        "provider_profile": "email-profile-deferred",
    }

    result = execute_dispatch_with_mock_provider(
        dispatch,
        executed_at="2026-09-12T14:02:00Z",
    )

    assert result["execution_status"] == "SKIPPED"
    assert result["recommended_action"] is None
    assert result["channel_type"] == "EMAIL"
    assert result["provider_profile"] == "mock-default"
    assert result["safe_result_preview"] == (
        "Dispatch execution skipped because live outbound delivery is deferred in S72."
    )
    assert result["redaction"]["raw_notification_payload_included"] is False


def test_mock_dispatch_execution_provider_rejects_unknown_profile() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc_info:
        build_mock_dispatch_execution_provider("unknown-profile")

    assert exc_info.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_provider_profile_unsupported"
    )


def test_notification_provider_request_shape_is_safe_and_redacted() -> None:
    dispatch = sample_live_channel_dispatch(
        channel_type="EMAIL",
        dispatch_intent="NOTIFY_OWNER",
        provider_profile="email-notification-default",
        safe_subject="SLA warning for case-0723",
        safe_body="Notify the assigned owner that the review case is near SLA.",
        provider_payload_fingerprint="safe-provider-payload-fingerprint",
    )
    config = build_dispatch_execution_provider_config(
        {
            DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http",
            DISPATCH_LIVE_PROVIDER_PROFILE_ENV: "email-notification-default",
            DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: "https://notify.invalid/path/secret",
            DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0723",
        }
    )

    request = build_notification_dispatch_provider_request(
        dispatch,
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at="2026-09-13T09:00:00Z",
    )

    assert request["provider_request_schema_version"] == (
        DISPATCH_NOTIFICATION_PROVIDER_REQUEST_SCHEMA_VERSION
    )
    assert request["provider_category"] == "notification"
    assert request["provider_type"] == "email_notification"
    assert request["provider_profile"] == "email-notification-default"
    assert request["provider_mode"] == "mock_http"
    assert request["dispatch_id"] == dispatch["dispatch_id"]
    assert request["channel_type"] == "EMAIL"
    assert request["safe_payload"]["safe_subject"] == "SLA warning for case-0723"
    assert request["safe_payload"]["safe_body_hash"] == dispatch["safe_body_hash"]
    assert request["safe_payload"]["provider_payload_hash"] == (
        dispatch["provider_payload_hash"]
    )
    assert request["http"]["method"] == "POST"
    assert request["http"]["endpoint_hint"] == "https://notify.invalid/<redacted>"
    assert request["http"]["token_configured"] is True
    assert request["activation"]["live_network_calls_enabled"] is False
    assert request["idempotency_hash"]
    serialized = json.dumps(request)
    assert "https://notify.invalid/path/secret" not in serialized
    assert "notify-token-0723" not in serialized
    assert "safe-provider-payload-fingerprint" not in serialized
    assert_dispatch_execution_result_redacted(request)


def test_notification_provider_request_rejects_non_notification_channel() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc_info:
        build_notification_dispatch_provider_request(sample_dispatch())

    assert exc_info.value.error_code == (
        "ag.operator_review_escalation_dispatch_notification_channel_unsupported"
    )


def test_notification_provider_request_fallback_profiles_and_config_defaults() -> None:
    email_request = build_notification_dispatch_provider_request(
        sample_live_channel_dispatch(
            channel_type="EMAIL",
            reason_codes="not-a-list",
        ),
        provider_config={"effective_provider_mode": "mock_http"},
        requested_at="2026-09-13T09:05:00Z",
    )
    assert email_request["provider_profile"] == "email-notification-default"
    assert email_request["safe_payload"]["reason_codes"] == []
    assert email_request["http"]["endpoint_configured"] is False
    assert email_request["http"]["timeout_seconds"] == 15.0

    webhook_request = build_notification_dispatch_provider_request(
        sample_live_channel_dispatch(
            channel_type="WEBHOOK",
            provider_profile="notification-webhook-default",
        ),
        provider_config={
            "effective_provider_mode": "mock_http",
            "live_provider_profile": "email-notification-default",
        },
        requested_at="2026-09-13T09:06:00Z",
    )
    assert webhook_request["provider_profile"] == "notification-webhook-default"
    assert webhook_request["provider_type"] == "notification_webhook"

    malformed_endpoint = build_notification_dispatch_provider_request(
        sample_live_channel_dispatch(channel_type="WEBHOOK"),
        provider_config={
            "effective_provider_mode": "mock_http",
            "endpoints": {"notification": "not-a-dict"},
        },
    )
    assert malformed_endpoint["http"]["endpoint_configured"] is False


def test_mock_notification_provider_success_retry_and_failure_are_safe() -> None:
    dispatch = sample_live_channel_dispatch(
        channel_type="WEBHOOK",
        dispatch_intent="NOTIFY_OPERATOR",
        provider_profile="notification-webhook-default",
        safe_subject="Dispatch webhook",
        safe_body="Send a bounded dispatch notification.",
    )
    config = build_dispatch_execution_provider_config(
        {DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http"}
    )
    provider = MockNotificationDispatchProvider()

    success = provider.execute(
        dispatch,
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        status_code=202,
        executed_at="2026-09-13T09:10:00Z",
    )

    assert success["execution_status"] == "SUCCEEDED"
    assert success["recommended_action"] == "SUCCEED"
    assert success["provider_category"] == "notification"
    assert success["provider_profile"] == "notification-webhook-default"
    assert success["provider_mode"] == "mock_http"
    assert success["http_status_code"] == 202
    assert success["safe_result_preview"] == (
        "Mock notification provider accepted dispatch."
    )
    assert success["retryable"] is False
    assert success["provider_request_hash"]
    assert_dispatch_execution_result_redacted(success)

    retry = execute_dispatch_with_mock_notification_provider(
        dispatch,
        provider_config=config,
        status_code=503,
        executed_at="2026-09-13T09:11:00Z",
    )
    assert retry["execution_status"] == "RETRY_WAIT"
    assert retry["recommended_action"] == "RETRY"
    assert retry["retryable"] is True
    assert retry["last_error_code"] == "notification_provider_retryable_status"
    assert retry["next_attempt_at"] == "2026-09-13T09:16:00Z"

    failed = execute_dispatch_with_mock_notification_provider(
        dispatch,
        provider_config=config,
        status_code=400,
        executed_at="2026-09-13T09:12:00Z",
    )
    assert failed["execution_status"] == "FAILED"
    assert failed["recommended_action"] == "FAIL"
    assert failed["retryable"] is False
    assert failed["last_error_code"] == "notification_provider_rejected"
    assert "raw_notification_payload" in json.dumps(failed)
    assert "RAW_NOTIFICATION_PAYLOAD" not in json.dumps(failed)


def test_provider_adapter_result_requires_failure_and_retry_context() -> None:
    dispatch = sample_live_channel_dispatch(channel_type="EMAIL")
    provider_request = build_notification_dispatch_provider_request(dispatch)

    with pytest.raises(OperatorReviewNoteError) as failed_exc:
        _build_provider_adapter_execution_result(
            dispatch,
            provider_request,
            execution_status="FAILED",
            safe_result_message="missing error",
        )
    assert failed_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_error_code_required"
    )

    with pytest.raises(OperatorReviewNoteError) as retry_exc:
        _build_provider_adapter_execution_result(
            dispatch,
            provider_request,
            execution_status="RETRY_WAIT",
            safe_result_message="missing retry timestamp",
            last_error_code="notification_provider_retryable_status",
        )
    assert retry_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_retry_at_required"
    )


def test_external_incident_provider_request_shape_is_safe_and_redacted() -> None:
    dispatch = sample_live_channel_dispatch(
        channel_type="INCIDENT",
        dispatch_intent="OPEN_INCIDENT",
        provider_profile="external-incident-default",
        safe_subject="Open incident for case-0724",
        safe_body="Create an external incident with bounded context only.",
        provider_payload_fingerprint="incident-provider-fingerprint",
    )
    config = build_dispatch_execution_provider_config(
        {
            DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http",
            DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV: (
                "https://incident.invalid/api/cases/secret"
            ),
            DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV: "incident-token-0724",
        }
    )

    request = build_external_incident_dispatch_provider_request(
        dispatch,
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at="2026-09-13T10:00:00Z",
    )

    assert request["provider_request_schema_version"] == (
        DISPATCH_EXTERNAL_INCIDENT_PROVIDER_REQUEST_SCHEMA_VERSION
    )
    assert request["provider_category"] == "external_incident"
    assert request["provider_type"] == "external_incident"
    assert request["provider_profile"] == "external-incident-default"
    assert request["provider_mode"] == "mock_http"
    assert request["channel_type"] == "INCIDENT"
    assert request["incident_payload"]["safe_subject"] == (
        "Open incident for case-0724"
    )
    assert request["incident_payload"]["target_ref"]["target_service"] == "nex-ag"
    assert request["incident_payload"]["target_ref"]["target_id_hash"]
    assert request["incident_payload"]["provider_payload_hash"] == (
        dispatch["provider_payload_hash"]
    )
    assert request["http"]["method"] == "POST"
    assert request["http"]["endpoint_hint"] == (
        "https://incident.invalid/<redacted>"
    )
    assert request["http"]["token_configured"] is True
    serialized = json.dumps(request)
    assert "https://incident.invalid/api/cases/secret" not in serialized
    assert "incident-token-0724" not in serialized
    assert "incident-provider-fingerprint" not in serialized
    assert dispatch["target_id"] not in serialized
    assert_dispatch_execution_result_redacted(request)


def test_external_incident_provider_request_rejects_non_incident_channel() -> None:
    with pytest.raises(OperatorReviewNoteError) as exc_info:
        build_external_incident_dispatch_provider_request(
            sample_live_channel_dispatch(channel_type="EMAIL")
        )

    assert exc_info.value.error_code == (
        "ag.operator_review_escalation_dispatch_external_incident_channel_unsupported"
    )


def test_mock_external_incident_provider_success_retry_and_failure_are_safe() -> None:
    dispatch = sample_live_channel_dispatch(
        channel_type="INCIDENT",
        dispatch_intent="OPEN_INCIDENT",
        provider_profile="external-incident-default",
        safe_subject="Incident dispatch",
        safe_body="Open an incident with bounded context.",
    )
    config = build_dispatch_execution_provider_config(
        {DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http"}
    )
    provider = MockExternalIncidentDispatchProvider()

    success = provider.execute(
        dispatch,
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        status_code=201,
        executed_at="2026-09-13T10:10:00Z",
    )

    assert success["execution_status"] == "SUCCEEDED"
    assert success["recommended_action"] == "SUCCEED"
    assert success["provider_category"] == "external_incident"
    assert success["provider_profile"] == "external-incident-default"
    assert success["http_status_code"] == 201
    assert success["safe_result_preview"] == (
        "Mock external incident provider accepted dispatch."
    )
    assert success["retryable"] is False
    assert_dispatch_execution_result_redacted(success)

    duplicate = execute_dispatch_with_mock_external_incident_provider(
        dispatch,
        provider_config=config,
        status_code=409,
        executed_at="2026-09-13T10:11:00Z",
    )
    assert duplicate["execution_status"] == "SUCCEEDED"
    assert duplicate["http_status_code"] == 409

    retry = execute_dispatch_with_mock_external_incident_provider(
        dispatch,
        provider_config=config,
        status_code=500,
        executed_at="2026-09-13T10:12:00Z",
    )
    assert retry["execution_status"] == "RETRY_WAIT"
    assert retry["recommended_action"] == "RETRY"
    assert retry["retryable"] is True
    assert retry["last_error_code"] == "external_incident_provider_retryable_status"
    assert retry["next_attempt_at"] == "2026-09-13T10:17:00Z"

    failed = execute_dispatch_with_mock_external_incident_provider(
        dispatch,
        provider_config=config,
        status_code=422,
        executed_at="2026-09-13T10:13:00Z",
    )
    assert failed["execution_status"] == "FAILED"
    assert failed["recommended_action"] == "FAIL"
    assert failed["retryable"] is False
    assert failed["last_error_code"] == "external_incident_provider_rejected"
    assert "raw_external_incident_payload" in json.dumps(failed)
    assert "RAW_EXTERNAL_INCIDENT_PAYLOAD" not in json.dumps(failed)


def test_dispatch_provider_http_client_retries_then_succeeds_safely() -> None:
    dispatch = sample_live_channel_dispatch(channel_type="WEBHOOK")
    request = build_notification_dispatch_provider_request(
        dispatch,
        provider_config=build_dispatch_execution_provider_config(
            {
                DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http",
                DISPATCH_HTTP_MAX_RETRIES_ENV: "2",
            }
        ),
    )
    transport = MockDispatchProviderHttpTransport(status_codes=(429, 202))

    result = execute_dispatch_provider_http_request(
        request,
        transport=transport,
        executed_at="2026-09-13T11:00:00Z",
    )

    assert result["http_client_result_schema_version"] == (
        DISPATCH_PROVIDER_HTTP_CLIENT_RESULT_SCHEMA_VERSION
    )
    assert result["provider_request_schema_version"] == (
        DISPATCH_NOTIFICATION_PROVIDER_REQUEST_SCHEMA_VERSION
    )
    assert result["execution_status"] == "SUCCEEDED"
    assert result["recommended_action"] == "SUCCEED"
    assert result["attempt_count"] == 2
    assert result["max_attempts"] == 3
    assert result["http_status_code"] == 202
    assert result["retryable"] is False
    assert result["last_error_code"] is None
    assert result["response_body_hash"]
    assert_dispatch_execution_result_redacted(result)


def test_dispatch_provider_http_client_timeout_and_rejection_paths() -> None:
    dispatch = sample_live_channel_dispatch(channel_type="INCIDENT")
    request = build_external_incident_dispatch_provider_request(dispatch)

    timeout = execute_dispatch_provider_http_request(
        request,
        transport=MockDispatchProviderHttpTransport(
            status_codes=(202,),
            timeout_attempts=(1, 2, 3),
        ),
        provider_config=build_dispatch_execution_provider_config(
            {DISPATCH_HTTP_MAX_RETRIES_ENV: "2"}
        ),
        executed_at="2026-09-13T11:05:00Z",
    )
    assert timeout["execution_status"] == "RETRY_WAIT"
    assert timeout["recommended_action"] == "RETRY"
    assert timeout["attempt_count"] == 3
    assert timeout["http_status_code"] is None
    assert timeout["retryable"] is True
    assert timeout["last_error_code"] == "dispatch_provider_http_timeout"
    assert timeout["next_attempt_at"] == "2026-09-13T11:10:00Z"

    retryable_status = execute_dispatch_provider_http_request(
        request,
        transport=MockDispatchProviderHttpTransport(status_codes=(503, 503)),
        provider_config=build_dispatch_execution_provider_config(
            {DISPATCH_HTTP_MAX_RETRIES_ENV: "1"}
        ),
        executed_at="2026-09-13T11:05:30Z",
    )
    assert retryable_status["execution_status"] == "RETRY_WAIT"
    assert retryable_status["attempt_count"] == 2
    assert retryable_status["http_status_code"] == 503
    assert retryable_status["last_error_code"] == (
        "dispatch_provider_http_retryable_status"
    )

    rejected = execute_dispatch_provider_http_request(
        request,
        transport=MockDispatchProviderHttpTransport(status_codes=(400,)),
        executed_at="2026-09-13T11:06:00Z",
    )
    assert rejected["execution_status"] == "FAILED"
    assert rejected["recommended_action"] == "FAIL"
    assert rejected["attempt_count"] == 1
    assert rejected["http_status_code"] == 400
    assert rejected["retryable"] is False
    assert rejected["last_error_code"] == "dispatch_provider_http_rejected"


def test_dispatch_provider_http_client_guard_and_malformed_response_paths() -> None:
    request = build_notification_dispatch_provider_request(
        sample_live_channel_dispatch(channel_type="EMAIL")
    )

    with pytest.raises(OperatorReviewNoteError) as transport_exc:
        execute_dispatch_provider_http_request(request, transport=None)
    assert transport_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_provider_http_transport_required"
    )

    class MalformedTransport:
        def send(self, *_: Any, **__: Any) -> dict[str, Any]:
            return {"status_code": "not-an-int"}

    malformed = execute_dispatch_provider_http_request(
        request,
        transport=MalformedTransport(),
        executed_at="2026-09-13T11:07:00Z",
    )
    assert malformed["execution_status"] == "FAILED"
    assert malformed["http_status_code"] == 0

    with pytest.raises(OperatorReviewNoteError) as failed_exc:
        _build_dispatch_provider_http_client_result(
            request,
            http_settings=request["http"],
            execution_status="FAILED",
            attempt_count=1,
            http_status_code=400,
            response_body_hash=None,
        )
    assert failed_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_error_code_required"
    )

    with pytest.raises(OperatorReviewNoteError) as retry_exc:
        _build_dispatch_provider_http_client_result(
            request,
            http_settings=request["http"],
            execution_status="RETRY_WAIT",
            attempt_count=1,
            http_status_code=429,
            response_body_hash=None,
            last_error_code="dispatch_provider_http_retryable_status",
        )
    assert retry_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_retry_at_required"
    )


def test_dispatch_live_http_transport_envelope_and_urllib_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = build_notification_dispatch_provider_request(
        sample_live_channel_dispatch(
            channel_type="WEBHOOK",
            safe_body="Safe live HTTP transport message.",
        ),
        provider_config=build_dispatch_execution_provider_config(
            {DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "live_http"}
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at="2026-09-14T09:00:00Z",
    )
    envelope = build_dispatch_live_http_transport_envelope(
        request,
        attempt_number=2,
    )

    assert envelope["transport_envelope_schema_version"] == (
        DISPATCH_LIVE_HTTP_TRANSPORT_ENVELOPE_SCHEMA_VERSION
    )
    assert envelope["provider_category"] == "notification"
    assert envelope["attempt_number"] == 2
    assert envelope["safe_payload"]["safe_body_hash"]
    assert "Safe live HTTP transport message." in json.dumps(envelope)
    assert "service-token" not in json.dumps(envelope)
    assert_dispatch_execution_result_redacted(envelope)

    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def getcode(self) -> int:
            return 202

        def read(self, _: int) -> bytes:
            return b'{"accepted":true}'

    def fake_urlopen(req: Any, *, timeout: float) -> FakeResponse:
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(dispatch_execution, "urlopen", fake_urlopen)
    transport = build_dispatch_live_http_transport(
        request,
        endpoint_url="http://127.0.0.1:0/dispatch/notification",
        bearer_token="transport-token-0732",
    )
    result = transport.send(request, attempt_number=2, timeout_seconds=7.5)

    assert result["status_code"] == 202
    assert result["response_body_hash"] == sha256_text('{"accepted":true}')
    assert captured["url"] == "http://127.0.0.1:0/dispatch/notification"
    assert captured["timeout"] == 7.5
    assert captured["headers"]["Authorization"] == "Bearer transport-token-0732"
    assert captured["headers"]["X-nex-dispatch-attempt"] == "2"
    assert captured["body"]["provider_request_hash"] == request["provider_request_hash"]
    assert "transport-token-0732" not in json.dumps(result)


def test_dispatch_live_http_transport_request_plan_redacts_headers_and_endpoint() -> None:
    endpoint = "https://notify.internal.example/hook/secret/path"
    request = build_notification_dispatch_provider_request(
        sample_live_channel_dispatch(channel_type="EMAIL"),
        provider_config=build_dispatch_execution_provider_config(
            {
                DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "live_http",
                DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: endpoint,
                DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "request-plan-token-0733",
            }
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    raw_headers = build_dispatch_live_http_transport_headers(
        request,
        attempt_number=0,
        bearer_token="request-plan-token-0733",
        user_agent=None,
    )
    plan = build_dispatch_live_http_transport_request_plan(
        request,
        endpoint_url=endpoint,
        attempt_number=0,
        bearer_token_configured=True,
    )

    assert raw_headers["Authorization"] == "Bearer request-plan-token-0733"
    assert raw_headers["X-NEX-Dispatch-Attempt"] == "1"
    assert raw_headers["X-NEX-Trace-Id"] == TRACE_ID
    assert plan["transport_request_plan_schema_version"] == (
        DISPATCH_LIVE_HTTP_TRANSPORT_REQUEST_PLAN_SCHEMA_VERSION
    )
    assert plan["endpoint_hint"] == "https://notify.internal.example/<redacted>"
    assert plan["method"] == "POST"
    assert plan["attempt_number"] == 1
    assert plan["authorization_header_configured"] is True
    assert plan["withheld_header_names"] == ["Authorization"]
    assert "Authorization" not in plan["evidence_header_names"]
    assert "X-NEX-Dispatch-Request-Hash" in plan["evidence_header_names"]
    assert endpoint not in json.dumps(plan)
    assert "request-plan-token-0733" not in json.dumps(plan)
    assert plan["raw_header_values_in_evidence_allowed"] is False
    assert_dispatch_execution_result_redacted(plan)

    plan_without_token = build_dispatch_live_http_transport_request_plan(
        request,
        endpoint_url="http://127.0.0.1:43199/dispatch",
        attempt_number=3,
    )
    assert plan_without_token["withheld_header_names"] == []
    assert plan_without_token["authorization_header_configured"] is False


def test_dispatch_live_http_transport_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = build_external_incident_dispatch_provider_request(
        sample_live_channel_dispatch(
            channel_type="INCIDENT",
            provider_profile="external-incident-default",
        )
    )

    with pytest.raises(OperatorReviewNoteError) as endpoint_exc:
        build_dispatch_live_http_transport(
            request,
            endpoint_url="not-a-url",
        )
    assert endpoint_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_live_http_endpoint_invalid"
    )

    with pytest.raises(OperatorReviewNoteError) as category_exc:
        build_dispatch_live_http_transport(
            {**request, "provider_category": "pager"},
            endpoint_url="http://127.0.0.1:0/dispatch",
        )
    assert category_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_live_http_transport_category_unsupported"
    )

    def fake_http_error(*_: Any, **__: Any) -> None:
        raise HTTPError(
            "http://127.0.0.1:0/dispatch",
            429,
            "too many requests",
            {},
            BytesIO(b"retry later"),
        )

    monkeypatch.setattr(dispatch_execution, "urlopen", fake_http_error)
    transport = build_dispatch_live_http_transport(
        request,
        endpoint_url="http://127.0.0.1:0/dispatch",
    )
    retryable = transport.send(request, attempt_number=1, timeout_seconds=1)
    assert retryable["status_code"] == 429
    assert retryable["response_body_hash"] == sha256_text("retry later")

    def fake_url_error(*_: Any, **__: Any) -> None:
        raise URLError("connection refused")

    monkeypatch.setattr(dispatch_execution, "urlopen", fake_url_error)
    refused = transport.send(request, attempt_number=1, timeout_seconds=1)
    assert refused["status_code"] == 0
    assert refused["response_body_hash"] == sha256_text("str")

    def fake_timeout(*_: Any, **__: Any) -> None:
        raise TimeoutError("loopback timeout")

    monkeypatch.setattr(dispatch_execution, "urlopen", fake_timeout)
    with pytest.raises(TimeoutError):
        transport.send(request, attempt_number=1, timeout_seconds=1)

    def fake_url_timeout(*_: Any, **__: Any) -> None:
        raise URLError(TimeoutError("loopback url timeout"))

    monkeypatch.setattr(dispatch_execution, "urlopen", fake_url_timeout)
    with pytest.raises(TimeoutError):
        transport.send(request, attempt_number=1, timeout_seconds=1)


def test_dispatch_live_http_transport_adapter_maps_http_results() -> None:
    config = build_dispatch_execution_provider_config(
        {
            DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "live_http",
            DISPATCH_LIVE_PROVIDER_ENABLE_ENV: "1",
            DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: "http://127.0.0.1:43199/notify",
            DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0734",
            DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV: (
                "http://127.0.0.1:43199/incident"
            ),
            DISPATCH_EXTERNAL_INCIDENT_TOKEN_ENV: "incident-token-0734",
            DISPATCH_HTTP_MAX_RETRIES_ENV: "0",
        }
    )
    notification = sample_live_channel_dispatch(
        dispatch_id="dispatch-0734-notification",
        channel_type="EMAIL",
        provider_profile="email-notification-default",
    )
    incident = sample_live_channel_dispatch(
        dispatch_id="dispatch-0734-incident",
        channel_type="INCIDENT",
        provider_profile="external-incident-default",
    )

    success = execute_dispatch_with_live_http_transport(
        notification,
        transport=MockDispatchProviderHttpTransport(status_codes=(202,)),
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        executed_at="2026-09-14T09:20:00Z",
    )
    assert success["execution_status"] == "SUCCEEDED"
    assert success["provider_mode"] == "live_http"
    assert success["provider_category"] == "notification"
    assert success["http_status_code"] == 202
    assert success["attempt_count"] == 1
    assert success["response_body_hash"]
    assert success["safe_result_preview"] == (
        "Live HTTP notification provider accepted dispatch."
    )
    assert_dispatch_execution_result_redacted(success)

    retry = execute_dispatch_with_live_http_transport(
        incident,
        transport=MockDispatchProviderHttpTransport(status_codes=(503,)),
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        executed_at="2026-09-14T09:21:00Z",
    )
    assert retry["execution_status"] == "RETRY_WAIT"
    assert retry["recommended_action"] == "RETRY"
    assert retry["provider_category"] == "external_incident"
    assert retry["http_status_code"] == 503
    assert retry["last_error_code"] == "dispatch_provider_http_retryable_status"
    assert retry["next_attempt_at"] == "2026-09-14T09:26:00Z"
    assert retry["safe_result_preview"] == (
        "Live HTTP external_incident provider returned a retryable result."
    )

    failed = execute_dispatch_with_live_http_transport(
        notification,
        transport=MockDispatchProviderHttpTransport(status_codes=(400,)),
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        executed_at="2026-09-14T09:22:00Z",
    )
    assert failed["execution_status"] == "FAILED"
    assert failed["recommended_action"] == "FAIL"
    assert failed["last_error_code"] == "dispatch_provider_http_rejected"
    assert failed["safe_result_preview"] == (
        "Live HTTP notification provider rejected dispatch."
    )

    with pytest.raises(OperatorReviewNoteError) as channel_exc:
        execute_dispatch_with_live_http_transport(
            {**notification, "channel_type": "SMS"},
            transport=MockDispatchProviderHttpTransport(),
            provider_config=config,
        )
    assert channel_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_live_http_channel_unsupported"
    )


def test_dispatch_provider_router_preserves_mock_first_and_routes_live_channels() -> None:
    config = build_dispatch_execution_provider_config(
        {DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http"}
    )
    email_dispatch = sample_live_channel_dispatch(
        channel_type="EMAIL",
        provider_profile="email-notification-default",
    )
    incident_dispatch = sample_live_channel_dispatch(
        channel_type="INCIDENT",
        provider_profile="external-incident-default",
    )

    skipped = execute_dispatch_with_provider_router(
        email_dispatch,
        provider_mode="mock_first_only",
        provider_config=config,
        executed_at="2026-09-13T12:00:00Z",
    )
    assert skipped["execution_status"] == "SKIPPED"
    assert skipped["provider_profile"] == "mock-default"

    notification = execute_dispatch_with_provider_router(
        email_dispatch,
        provider_mode="mock_http",
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        notification_status_code=202,
        executed_at="2026-09-13T12:01:00Z",
    )
    assert notification["execution_status"] == "SUCCEEDED"
    assert notification["provider_category"] == "notification"
    assert notification["provider_mode"] == "mock_http"

    live_config = build_dispatch_execution_provider_config(
        {
            DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "live_http",
            DISPATCH_LIVE_PROVIDER_ENABLE_ENV: "1",
            DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: "http://127.0.0.1:43199/notify",
            DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0737",
        }
    )
    live = execute_dispatch_with_provider_router(
        email_dispatch,
        provider_mode="live_http",
        provider_config=live_config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        live_http_transport=MockDispatchProviderHttpTransport(status_codes=(202,)),
        executed_at="2026-09-14T10:37:00Z",
    )
    assert live["execution_status"] == "SUCCEEDED"
    assert live["provider_mode"] == "live_http"
    assert live["provider_category"] == "notification"
    assert live["http_status_code"] == 202

    with pytest.raises(OperatorReviewNoteError) as transport_exc:
        execute_dispatch_with_provider_router(
            email_dispatch,
            provider_mode="live_http",
            provider_config=live_config,
        )
    assert transport_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_provider_http_transport_required"
    )

    incident = execute_dispatch_with_provider_router(
        incident_dispatch,
        provider_mode="mock_http",
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        external_incident_status_code=500,
        executed_at="2026-09-13T12:02:00Z",
    )
    assert incident["execution_status"] == "RETRY_WAIT"
    assert incident["provider_category"] == "external_incident"
    assert incident["last_error_code"] == (
        "external_incident_provider_retryable_status"
    )

    with pytest.raises(OperatorReviewNoteError) as channel_exc:
        execute_dispatch_with_provider_router(
            {**email_dispatch, "channel_type": "SMS"},
            provider_mode="mock_http",
            provider_config=config,
        )
    assert channel_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_router_channel_unsupported"
    )


def test_dispatch_execution_transition_plan_success_actions_apply_to_state_machine() -> None:
    dispatch = sample_dispatch()
    result = execute_dispatch_with_mock_provider(
        dispatch,
        executed_at="2026-09-12T15:00:00Z",
    )

    plan = build_dispatch_execution_transition_plan(
        dispatch,
        result,
        planned_at="2026-09-12T15:00:00Z",
    )

    assert plan["transition_plan_schema_version"].endswith(".v1")
    assert plan["plan_status"] == "READY"
    assert [action["action_type"] for action in plan["actions"]] == [
        "START",
        "SUCCEED",
    ]
    started, _ = apply_operator_review_escalation_dispatch_action(
        dispatch,
        plan["actions"][0],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0715-start",
        acted_at="2026-09-12T15:00:00Z",
    )
    succeeded, action = apply_operator_review_escalation_dispatch_action(
        started,
        plan["actions"][1],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="idem-0715-succeed",
        acted_at="2026-09-12T15:01:00Z",
    )

    assert action["action_type"] == "SUCCEED"
    assert succeeded["dispatch_status"] == "SUCCEEDED"
    assert succeeded["metadata"]["last_action_type"] == "SUCCEED"


def test_dispatch_execution_transition_plan_failure_retry_and_failed_row_paths() -> None:
    dispatch = sample_dispatch(provider_profile="mock-failure")
    result = execute_dispatch_with_mock_provider(
        dispatch,
        profile_id="mock-failure",
        executed_at="2026-09-12T15:10:00Z",
    )

    plan = build_dispatch_execution_transition_plan(
        dispatch,
        result,
        planned_at="2026-09-12T15:10:00Z",
    )

    assert [action["action_type"] for action in plan["actions"]] == [
        "START",
        "FAIL",
        "RETRY",
    ]
    assert plan["actions"][1]["last_error_code"] == "mock_dispatch_failed"
    assert plan["actions"][2]["next_attempt_at"] == "2026-09-12T15:15:00Z"

    failed_row = {
        **dispatch,
        "dispatch_status": "FAILED",
        "attempt_count": 1,
    }
    retry_plan = build_dispatch_execution_transition_plan(
        failed_row,
        result,
        planned_at="2026-09-12T15:20:00Z",
    )
    assert retry_plan["plan_status"] == "READY"
    assert [action["action_type"] for action in retry_plan["actions"]] == ["RETRY"]
    assert retry_plan["actions"][0]["next_attempt_at"] == "2026-09-12T15:25:00Z"

    exhausted = build_dispatch_execution_transition_plan(
        {**failed_row, "attempt_count": 3},
        result,
        planned_at="2026-09-12T15:30:00Z",
    )
    assert exhausted["plan_status"] == "BLOCKED"
    assert exhausted["skip_reason"] == "max_attempts_exhausted"

    non_retryable_dispatch = sample_dispatch()
    non_retryable_result = build_dispatch_execution_result(
        non_retryable_dispatch,
        execution_status="FAILED",
        last_error_code="mock_non_retryable_failure",
    )
    non_retryable_plan = build_dispatch_execution_transition_plan(
        {**non_retryable_dispatch, "attempt_count": "not-a-number"},
        non_retryable_result,
        planned_at="2026-09-12T15:35:00Z",
    )
    assert non_retryable_plan["attempt_count"] == 0
    assert [action["action_type"] for action in non_retryable_plan["actions"]] == [
        "START",
        "FAIL",
    ]


def test_dispatch_execution_transition_plan_skip_and_retry_wait_paths() -> None:
    terminal = build_dispatch_execution_transition_plan(
        {**sample_dispatch(), "dispatch_status": "SUCCEEDED"},
        planned_at="2026-09-12T15:40:00Z",
    )
    assert terminal["plan_status"] == "SKIPPED"
    assert terminal["skip_reason"] == "terminal_dispatch_status"

    in_progress = build_dispatch_execution_transition_plan(
        {**sample_dispatch(), "dispatch_status": "DISPATCHING"},
        planned_at="2026-09-12T15:41:00Z",
    )
    assert in_progress["skip_reason"] == "dispatch_already_in_progress"

    unsupported = build_dispatch_execution_transition_plan(
        {**sample_dispatch(), "dispatch_status": "UNKNOWN"},
        planned_at="2026-09-12T15:42:00Z",
    )
    assert unsupported["skip_reason"] == "unsupported_dispatch_status"

    retry_result = build_dispatch_execution_result(
        sample_dispatch(provider_profile="mock-failure"),
        execution_status="RETRY_WAIT",
        provider_profile="mock-failure",
        next_attempt_at="2026-09-12T16:00:00Z",
    )
    retry_wait_plan = build_dispatch_execution_transition_plan(
        sample_dispatch(provider_profile="mock-failure"),
        retry_result,
        planned_at="2026-09-12T15:45:00Z",
    )
    assert [action["action_type"] for action in retry_wait_plan["actions"]] == [
        "START",
        "FAIL",
        "RETRY",
    ]
    assert retry_wait_plan["actions"][2]["next_attempt_at"] == "2026-09-12T16:00:00Z"

    skipped_result = execute_dispatch_with_mock_provider(
        {**sample_dispatch(), "channel_type": "EMAIL"},
        executed_at="2026-09-12T15:50:00Z",
    )
    skipped_plan = build_dispatch_execution_transition_plan(
        {**sample_dispatch(), "channel_type": "EMAIL"},
        skipped_result,
        planned_at="2026-09-12T15:50:00Z",
    )
    assert skipped_plan["plan_status"] == "SKIPPED"
    assert skipped_plan["actions"] == []
    assert skipped_plan["skip_reason"] == "provider_execution_skipped"

    with pytest.raises(OperatorReviewNoteError) as unsupported_result_exc:
        build_dispatch_execution_transition_plan(
            sample_dispatch(),
            {"execution_status": "BOUNCED", "provider_result_hash": "x"},
            planned_at="2026-09-12T15:55:00Z",
        )
    assert unsupported_result_exc.value.error_code == (
        "ag.operator_review_escalation_dispatch_execution_result_status_unsupported"
    )


def test_dispatch_execution_worker_once_requires_confirmation() -> None:
    service, dispatch_store = build_dispatch_service(sample_dispatch())

    run = run_dispatch_execution_worker_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        executed_at="2026-09-12T16:00:00Z",
    )

    assert run["worker_run_schema_version"].endswith(".v1")
    assert run["run_status"] == "BLOCKED"
    assert run["blocked_reason"] == "confirm_run_required"
    assert run["candidate_count"] == 0
    assert dispatch_store.list_dispatches()[0]["dispatch_status"] == "PENDING"


def test_dispatch_execution_worker_once_processes_success_and_failure_batches() -> None:
    success = sample_dispatch(
        candidate_overrides={"candidate_id": "case-0716:success", "case_id": "case-0716-success"},
    )
    success_service, success_store = build_dispatch_service(success)

    success_run = run_dispatch_execution_worker_once(
        success_service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        batch_limit=1,
        confirm_run=True,
        executed_at="2026-09-12T16:05:00Z",
    )

    assert success_run["run_status"] == "COMPLETED"
    assert success_run["batch_limit"] == 1
    assert success_run["candidate_count"] == 1
    assert success_run["processed_count"] == 1
    assert success_run["succeeded_count"] == 1
    assert success_run["items"][0]["action_count"] == 2
    persisted_success = success_store.get(success["dispatch_id"])
    assert persisted_success["dispatch_status"] == "SUCCEEDED"
    success_metadata = persisted_success["metadata"]["last_execution_result"]
    assert success_metadata["execution_result_metadata_schema_version"].endswith(".v1")
    assert success_metadata["execution_status"] == "SUCCEEDED"
    assert success_metadata["provider_result_hash"]
    assert success_metadata["safe_result_preview"] == "Mock dispatch delivered."
    assert success_run["items"][0]["result_metadata_persisted"] is True

    failure = sample_dispatch(
        provider_profile="mock-failure",
        candidate_overrides={"candidate_id": "case-0716:failure", "case_id": "case-0716-failure"},
    )
    failure_service, failure_store = build_dispatch_service(failure)

    failure_run = run_dispatch_execution_worker_once(
        failure_service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        provider_profile="mock-failure",
        confirm_run=True,
        executed_at="2026-09-12T16:10:00Z",
    )

    assert failure_run["processed_count"] == 1
    assert failure_run["retry_wait_count"] == 1
    assert failure_run["items"][0]["final_status"] == "RETRY_WAIT"
    persisted_failure = failure_store.get(failure["dispatch_id"])
    assert persisted_failure["dispatch_status"] == "RETRY_WAIT"
    failure_metadata = persisted_failure["metadata"]["last_execution_result"]
    assert failure_metadata["execution_status"] == "FAILED"
    assert failure_metadata["last_error_code"] == "mock_dispatch_failed"
    assert failure_metadata["retryable"] is True
    assert "idem-0716" not in json.dumps(failure_run)


def test_dispatch_execution_worker_once_routes_live_channel_batches() -> None:
    email = sample_live_channel_dispatch(
        dispatch_id="dispatch-0726-email",
        channel_type="EMAIL",
        dispatch_intent="NOTIFY_OWNER",
        provider_profile="email-notification-default",
    )
    incident = sample_live_channel_dispatch(
        dispatch_id="dispatch-0726-incident",
        channel_type="INCIDENT",
        dispatch_intent="OPEN_INCIDENT",
        provider_profile="external-incident-default",
    )
    service, dispatch_store = build_dispatch_service(email, incident)
    config = build_dispatch_execution_provider_config(
        {DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "mock_http"}
    )

    run = run_dispatch_execution_worker_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        batch_limit=5,
        provider_mode="mock_http",
        provider_config=config,
        notification_status_code=202,
        external_incident_status_code=201,
        confirm_run=True,
        executed_at="2026-09-13T12:10:00Z",
    )

    assert run["run_status"] == "COMPLETED"
    assert run["candidate_count"] == 2
    assert run["processed_count"] == 2
    assert run["succeeded_count"] == 2
    assert {item["provider_profile"] for item in run["items"]} == {
        "email-notification-default",
        "external-incident-default",
    }
    persisted_email = dispatch_store.get("dispatch-0726-email")
    persisted_incident = dispatch_store.get("dispatch-0726-incident")
    assert persisted_email["dispatch_status"] == "SUCCEEDED"
    assert persisted_incident["dispatch_status"] == "SUCCEEDED"
    assert persisted_email["metadata"]["last_execution_result"]["provider_profile"] == (
        "email-notification-default"
    )
    assert persisted_email["metadata"]["last_execution_result"]["provider_category"] == (
        "notification"
    )
    assert persisted_email["metadata"]["last_execution_result"]["http_status_code"] == 202
    assert persisted_email["metadata"]["last_execution_result"]["provider_request_hash"]
    assert persisted_incident["metadata"]["last_execution_result"][
        "provider_profile"
    ] == "external-incident-default"
    assert persisted_incident["metadata"]["last_execution_result"][
        "provider_category"
    ] == "external_incident"
    assert persisted_incident["metadata"]["last_execution_result"][
        "http_status_code"
    ] == 201
    assert "notify-token" not in json.dumps(run)


def test_dispatch_execution_worker_once_routes_injected_live_http_transport() -> None:
    email = sample_live_channel_dispatch(
        dispatch_id="dispatch-0737-live-email",
        channel_type="EMAIL",
        dispatch_intent="NOTIFY_OWNER",
        provider_profile="email-notification-default",
    )
    service, dispatch_store = build_dispatch_service(email)
    config = build_dispatch_execution_provider_config(
        {
            DISPATCH_EXECUTION_PROVIDER_MODE_ENV: "live_http",
            DISPATCH_LIVE_PROVIDER_ENABLE_ENV: "1",
            DISPATCH_NOTIFICATION_WEBHOOK_URL_ENV: "http://127.0.0.1:43199/notify",
            DISPATCH_NOTIFICATION_SERVICE_TOKEN_ENV: "notify-token-0737-worker",
            DISPATCH_HTTP_MAX_RETRIES_ENV: "0",
        }
    )

    run = run_dispatch_execution_worker_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        batch_limit=5,
        provider_mode="live_http",
        provider_config=config,
        live_http_transport=MockDispatchProviderHttpTransport(status_codes=(202,)),
        confirm_run=True,
        executed_at="2026-09-14T10:37:30Z",
    )

    assert run["run_status"] == "COMPLETED"
    assert run["processed_count"] == 1
    assert run["succeeded_count"] == 1
    assert run["items"][0]["provider_profile"] == "email-notification-default"
    persisted = dispatch_store.get("dispatch-0737-live-email")
    assert persisted["dispatch_status"] == "SUCCEEDED"
    metadata = persisted["metadata"]["last_execution_result"]
    assert metadata["provider_mode"] == "live_http"
    assert metadata["provider_category"] == "notification"
    assert metadata["http_status_code"] == 202
    assert metadata["response_body_hash"]
    assert metadata["attempt_count"] == 1
    assert "notify-token-0737-worker" not in json.dumps(run)


def test_dispatch_execution_worker_once_dry_run_and_limit_bounds() -> None:
    dispatch = sample_dispatch()
    service, dispatch_store = build_dispatch_service(dispatch)

    dry_run = run_dispatch_execution_worker_once(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        batch_limit=999,
        confirm_run=True,
        dry_run=True,
        executed_at="2026-09-12T16:20:00Z",
    )

    assert dry_run["dry_run"] is True
    assert dry_run["batch_limit"] == 50
    assert dry_run["processed_count"] == 1
    assert dry_run["items"][0]["actions"] == []
    assert dispatch_store.get(dispatch["dispatch_id"])["dispatch_status"] == "PENDING"

    default_limit = run_dispatch_execution_worker_once(
        service,
        request_id=REQUEST_ID,
        batch_limit="invalid",  # type: ignore[arg-type]
        confirm_run=True,
        dry_run=True,
        executed_at="2026-09-12T16:21:00Z",
    )
    assert default_limit["batch_limit"] == 10


def test_dispatch_execution_result_metadata_helpers_are_safe() -> None:
    dispatch = sample_dispatch()
    result = execute_dispatch_with_mock_provider(
        dispatch,
        executed_at="2026-09-12T16:30:00Z",
    )

    metadata = build_dispatch_execution_result_metadata(
        result,
        run_id="run-0717",
        worker_id="worker-0717",
    )
    updated = record_dispatch_execution_result_metadata(
        dispatch,
        result,
        run_id="run-0717",
        worker_id="worker-0717",
    )

    assert metadata["execution_status"] == "SUCCEEDED"
    assert updated["metadata"]["last_execution_result"] == metadata
    assert updated["metadata"]["last_execution_result_recorded"] is True
    serialized = json.dumps(updated)
    assert "raw_provider_payload" in serialized
    assert "RAW_PROVIDER_PAYLOAD" not in serialized


def test_dispatch_execution_result_metadata_persist_guard_paths() -> None:
    result = execute_dispatch_with_mock_provider(sample_dispatch())

    assert (
        _persist_worker_result_metadata(
            object(),
            "",
            result,
            run_id="run-guard",
            worker_id="worker-guard",
        )
        is False
    )
    assert (
        _persist_worker_result_metadata(
            object(),
            "dispatch-guard",
            result,
            run_id="run-guard",
            worker_id="worker-guard",
        )
        is False
    )


def test_dispatch_execution_worker_candidate_deduplicates_invalid_ids() -> None:
    class FakeService:
        def list_escalation_dispatches(self, **_: Any) -> dict[str, Any]:
            return {
                "items": [
                    {"dispatch_id": "dispatch-0716-dup"},
                    {"dispatch_id": ""},
                    {"dispatch_id": "dispatch-0716-dup"},
                ]
            }

    candidates = _worker_candidate_dispatches(
        FakeService(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        limit=2,
    )

    assert candidates == [{"dispatch_id": "dispatch-0716-dup"}]
