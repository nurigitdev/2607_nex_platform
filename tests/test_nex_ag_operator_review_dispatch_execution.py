from __future__ import annotations

import json
from typing import Any

import pytest

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
    DISPATCH_EXECUTION_DEFAULT_PROVIDER_PROFILE,
    DISPATCH_EXECUTION_PROVIDER_CATALOG_SCHEMA_VERSION,
    DISPATCH_EXECUTION_PROVIDER_MODE,
    DISPATCH_EXECUTION_RESULT_SCHEMA_VERSION,
    assert_dispatch_execution_result_redacted,
    build_dispatch_execution_provider_catalog,
    build_dispatch_execution_result,
    build_dispatch_execution_transition_plan,
    build_mock_dispatch_execution_provider,
    execute_dispatch_with_mock_provider,
    normalize_dispatch_execution_provider_profile,
    run_dispatch_execution_worker_once,
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
    assert success_store.get(success["dispatch_id"])["dispatch_status"] == "SUCCEEDED"

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
    assert failure_store.get(failure["dispatch_id"])["dispatch_status"] == "RETRY_WAIT"
    assert "idem-0716" not in json.dumps(failure_run)


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
