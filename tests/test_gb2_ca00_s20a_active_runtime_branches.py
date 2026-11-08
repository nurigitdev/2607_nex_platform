from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
import run_gb2_ca00_s05_ae_agent_runtime_worker as ae_runner
import run_gb2_ca00_s06_wc_event_delivery_worker as wc_runner
import run_gb2_ca00_s07_eos_outbox_publisher as eos_runner
from nex_ae_api.approval_decision_event_api import (
    ApprovalDecisionEventError,
    HttpEosBusinessApprovalDecisionClient,
    _datetime,
    _delivery,
)
from nex_wc.work_results import SqlAlchemyWorkResultRepository, WorkResultError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class _FailingFactory:
    def __call__(self):
        raise SQLAlchemyError("database unavailable")


@pytest.mark.parametrize(
    "operation",
    (
        lambda repository: repository.get_submission_context(
            tenant_id="VO00", work_item_id="work-1"
        ),
        lambda repository: repository.get_result_source(
            tenant_id="VO00", result_id="result-1"
        ),
        lambda repository: repository.list_result_sources_by_execution(
            tenant_id="VO00", source_execution_ref="execution-1", limit=10
        ),
        lambda repository: repository.list_pending_result_events(limit=10),
        lambda repository: repository.load_result_event(
            outbox_id="outbox-1", event_id="event-1"
        ),
        lambda repository: repository.mark_result_event_enqueued(
            outbox_id="outbox-1",
            event_id="event-1",
            job_id="job-1",
            updated_at="2026-10-29T00:00:00Z",
        ),
        lambda repository: repository.mark_result_event_delivered(
            outbox_id="outbox-1",
            event_id="event-1",
            job_id="job-1",
            updated_at="2026-10-29T00:00:00Z",
        ),
    ),
)
def test_wc_sql_repository_maps_database_failures_to_retryable_error(operation) -> None:
    repository = SqlAlchemyWorkResultRepository(_FailingFactory())

    with pytest.raises(WorkResultError) as caught:
        operation(repository)

    assert caught.value.error_code == "wc.work_result_store_unavailable"
    assert caught.value.retryable is True


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _work_result() -> dict:
    return {
        "tenant_id": "VO00",
        "result_id": "result-1",
        "work_item_id": "work-1",
        "revision_no": 1,
        "result_type": "REPORT",
        "schema_ref": "urn:nex:result:1",
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": "execution-1",
        "claim_ref": "claim-1",
        "claim_generation": 1,
        "assignment_ref": "assignment-1",
        "submitted_by": {"entity_id": "agent-1"},
        "submitted_at": "2026-10-29T00:00:00Z",
        "trace": {"correlation_id": "trace-1"},
    }


def test_wc_sql_commit_maps_identity_race_and_storage_failure(monkeypatch) -> None:
    from nex_wc import work_results

    repository = SqlAlchemyWorkResultRepository(lambda: _Session())
    monkeypatch.setattr(
        work_results,
        "_load_result_by_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(
            IntegrityError("insert", {}, RuntimeError("duplicate"))
        ),
    )
    values = {
        "work_result": _work_result(),
        "result_hash": "sha256:" + "1" * 64,
        "expected_version": 2,
        "authorization": {
            "revision_hash": "sha256:" + "2" * 64,
            "checked_at": "2026-10-29T00:00:00Z",
        },
        "outbox_id": "outbox-1",
        "event_id": "event-1",
        "now": "2026-10-29T00:00:00Z",
    }

    with pytest.raises(WorkResultError) as caught:
        repository.commit_result(**values)
    assert caught.value.error_code == "wc.work_result_identity_conflict"

    monkeypatch.setattr(
        work_results,
        "_load_result_by_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(SQLAlchemyError("offline")),
    )
    with pytest.raises(WorkResultError) as unavailable:
        repository.commit_result(**values)
    assert unavailable.value.retryable is True


def _approval_delivery() -> dict:
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": "outbox-1",
        "work_item": {
            "tenant_id": "VO00",
            "approval_work_item_id": "work-1",
            "approval_domain": "BUSINESS_FORMAL",
        },
        "decision": {
            "tenant_id": "VO00",
            "approval_work_item_id": "work-1",
            "decision_id": "decision-1",
        },
        "event": {
            "tenant_id": "VO00",
            "approval_work_item_id": "work-1",
            "decision_id": "decision-1",
            "event_id": "event-1",
        },
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="wrong"), "schema"),
        (lambda value: value.update(work_item=[]), "must be an object"),
        (lambda value: value["work_item"].update(tenant_id="OTHER"), "lineage"),
        (lambda value: value["decision"].update(decision_id="OTHER"), "lineage"),
    ),
)
def test_approval_delivery_rejects_malformed_and_conflicting_lineage(
    mutation, message: str
) -> None:
    delivery = _approval_delivery()
    mutation(delivery)
    with pytest.raises(ApprovalDecisionEventError, match=message):
        _delivery(delivery)


@pytest.mark.parametrize("value", ("bad", "2026-10-29T00:00:00"))
def test_approval_delivery_rejects_invalid_decision_time(value: str) -> None:
    with pytest.raises(ApprovalDecisionEventError, match="decided_at"):
        _datetime(value)


@pytest.mark.parametrize(
    ("values", "message"),
    (
        ({"base_url": "", "service_token": "token"}, "base URL"),
        ({"base_url": "https://eos", "service_token": ""}, "service token"),
        (
            {
                "base_url": "https://eos",
                "service_token": "token",
                "timeout_seconds": True,
            },
            "timeout",
        ),
    ),
)
def test_eos_approval_client_rejects_malformed_configuration(values, message) -> None:
    with pytest.raises(ApprovalDecisionEventError, match=message):
        HttpEosBusinessApprovalDecisionClient(**values)


@pytest.mark.parametrize("failure", ("http", "network", "json"))
def test_eos_approval_client_classifies_transport_and_response_failures(
    failure: str,
) -> None:
    if failure == "http":

        def opener(request, **_kwargs):
            raise HTTPError(request.full_url, 503, "down", {}, BytesIO())

    elif failure == "network":

        def opener(_request, **_kwargs):
            raise URLError("offline")

    else:

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b"{"

        def opener(_request, **_kwargs):
            return Response()

    client = HttpEosBusinessApprovalDecisionClient(
        base_url="https://eos", service_token="token", opener=opener
    )
    with pytest.raises(ApprovalDecisionEventError) as caught:
        client.ingest(_approval_delivery())
    assert caught.value.retryable is True


@pytest.mark.parametrize("module", (ae_runner, wc_runner, eos_runner))
def test_canonical_runner_main_maps_pass_skip_and_failure(monkeypatch, module) -> None:
    runner_name = next(name for name in vars(module) if name.startswith("run_gb2_"))
    monkeypatch.setattr(module, "load_env_file", lambda _path: {})
    monkeypatch.setattr(
        module,
        runner_name,
        lambda _env: {"status": "PASS"},
    )
    assert module.main(["--summary", "--env-file", "missing.env"]) == 0
    monkeypatch.setattr(
        module,
        runner_name,
        lambda _env: {"status": "FAIL"},
    )
    assert module.main(["--summary", "--env-file", "missing.env"]) == 1
