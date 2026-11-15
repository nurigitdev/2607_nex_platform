from __future__ import annotations

import copy
import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
import test_nex_eos_mybee_project_pnl as fixture
from mybee_ax.integrations import nex_pnl_client as consumer_module
from mybee_ax.integrations.nex_pnl_client import (
    PROJECT_PNL_GET_OPERATION,
    HttpProjectPnlProviderTransport,
    NexProjectPnlClient,
    ProjectPnlConsumerError,
    admit_project_pnl_projection,
    build_project_pnl_request,
)

SUBJECT = "employee-pnl-reader"
CORRELATION = "mybee-pnl-query-1"


def _projection():
    runtime = fixture._runtime()
    try:
        return runtime.repository.append(fixture._draft(), fixture._components())
    finally:
        runtime.engine.dispose()


def _admit(value, **overrides):
    values = {
        "tenant_id": fixture.TENANT,
        "company_id": fixture.COMPANY_ID,
        "project_id": fixture.PROJECT_ID,
        "project_code": "W601D260001",
        "period_id": fixture.PERIOD_ID,
    }
    values.update(overrides)
    return admit_project_pnl_projection(value, **values)


def test_request_shape_latest_and_version_specific() -> None:
    latest = build_project_pnl_request(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
    )
    assert latest.method == "GET"
    assert latest.operation_id == PROJECT_PNL_GET_OPERATION
    assert latest.path.endswith(f"/{fixture.PROJECT_ID}/pnl/{fixture.PERIOD_ID}")

    versioned = build_project_pnl_request(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
        projection_version=3,
    )
    assert versioned.path.endswith("?projection_version=3")


def test_client_admits_strict_projection_and_preserves_immutable_view() -> None:
    projection = _projection()
    requests = []

    class Transport:
        def send(self, request):
            requests.append(request)
            return projection

    result = NexProjectPnlClient(Transport()).get(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        project_code="W601D260001",
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
        projection_version=1,
    )
    assert result["posted_operating_result"] == "600.0000"
    assert result["budget_variance"] == "100.0000"
    assert isinstance(result["components"], tuple)
    assert requests[0].subject_id == SUBJECT


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra="drift"),
        lambda value: value.pop("projection_hash"),
        lambda value: value.update(schema_version="eos_project_pnl_projection.v2"),
        lambda value: value.update(project_id="76000000-0000-4000-8000-000000000099"),
        lambda value: value.update(project_code="W601D269999"),
        lambda value: value.update(projection_version=0),
        lambda value: value.update(projection_version=True),
        lambda value: value.update(projection_version="bad"),
        lambda value: value.update(functional_currency="krw"),
        lambda value: value.update(as_of="2026-11-14T09:00:00"),
        lambda value: value.update(as_of=7),
        lambda value: value.update(as_of="not-a-timestamp"),
        lambda value: value.update(posting_watermark=None),
        lambda value: value.update(budget_watermark=None),
        lambda value: value.update(staleness_seconds=-1),
        lambda value: value.update(staleness_seconds=True),
        lambda value: value.update(staleness_seconds="bad"),
        lambda value: value.update(reconciliation_status="READY"),
        lambda value: value.update(freshness_status="FRESH"),
        lambda value: value.update(data_classification="PUBLIC"),
        lambda value: value.update(projection_hash="bad"),
        lambda value: value.update(components={}),
        lambda value: value.update(posted_revenue="1000.00"),
        lambda value: value.update(posted_revenue="999.0000"),
        lambda value: value.update(posted_operating_result="999.0000"),
        lambda value: value.update(budget_actual="999.0000"),
        lambda value: value.update(budget_variance="999.0000"),
    ],
)
def test_projection_contract_drift_fails_closed(mutation) -> None:
    value = copy.deepcopy(_projection())
    mutation(value)
    with pytest.raises(ProjectPnlConsumerError) as caught:
        _admit(value)
    assert caught.value.status_code in {400, 502}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.update(extra="drift"),
        lambda item: item.pop("component_hash"),
        lambda item: item.update(line_no=2),
        lambda item: item.update(classification="UNKNOWN"),
        lambda item: item.update(rollup_class="FORECAST"),
        lambda item: item.update(confirmed=False),
        lambda item: item.update(source_kind="PRIVATE_PAYROLL"),
        lambda item: item.update(account_id="bad"),
        lambda item: item.update(work_code=""),
        lambda item: item.update(functional_amount="0.0000"),
        lambda item: item.update(source_ref=""),
        lambda item: item.update(source_hash="bad"),
        lambda item: item.update(data_classification="PUBLIC"),
        lambda item: item.update(component_hash="bad"),
    ],
)
def test_component_contract_drift_fails_closed(mutation) -> None:
    value = copy.deepcopy(_projection())
    mutation(value["components"][0])
    with pytest.raises(ProjectPnlConsumerError) as caught:
        _admit(value)
    assert caught.value.error_code == "MYBEE_PNL_CONTRACT_DRIFT"


def test_duplicate_component_hash_and_future_watermark_fail_closed() -> None:
    duplicate = copy.deepcopy(_projection())
    duplicate["components"][1]["component_hash"] = duplicate["components"][0][
        "component_hash"
    ]
    with pytest.raises(ProjectPnlConsumerError, match="duplicated"):
        _admit(duplicate)

    future = copy.deepcopy(_projection())
    future["posting_watermark_at"] = "2026-11-15T09:00:00+00:00"
    with pytest.raises(ProjectPnlConsumerError, match="later than"):
        _admit(future)


def test_expected_version_and_project_code_binding_fail_closed() -> None:
    with pytest.raises(ProjectPnlConsumerError, match="version drifted"):
        _admit(_projection(), projection_version=2)
    with pytest.raises(ProjectPnlConsumerError) as project_code:
        _admit(_projection(), project_code="invalid")
    assert project_code.value.status_code == 400


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_id": "bad space"},
        {"company_id": "bad"},
        {"project_id": "bad"},
        {"period_id": "bad"},
        {"subject_id": ""},
        {"correlation_id": ""},
        {"projection_version": True},
        {"projection_version": 0},
        {"projection_version": "bad"},
    ],
)
def test_request_rejects_invalid_arguments(kwargs) -> None:
    values = {
        "tenant_id": fixture.TENANT,
        "company_id": fixture.COMPANY_ID,
        "project_id": fixture.PROJECT_ID,
        "period_id": fixture.PERIOD_ID,
        "subject_id": SUBJECT,
        "correlation_id": CORRELATION,
    }
    values.update(kwargs)
    with pytest.raises(ProjectPnlConsumerError) as caught:
        build_project_pnl_request(**values)
    assert caught.value.status_code == 400


class Response:
    def __init__(self, value) -> None:
        self._payload = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


def test_http_transport_sends_protected_scope_headers(monkeypatch) -> None:
    outgoing = []
    monkeypatch.setattr(
        consumer_module,
        "urlopen",
        lambda request, timeout: (
            outgoing.append((request, timeout)) or Response(_projection())
        ),
    )
    transport = HttpProjectPnlProviderTransport(
        eos_base_url="http://eos.local/base",
        service_token="signed-token",
        timeout_seconds=7,
    )
    request = build_project_pnl_request(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
    )
    assert transport.send(request)["project_id"] == fixture.PROJECT_ID
    sent, timeout = outgoing[0]
    assert timeout == 7
    assert sent.get_method() == "GET"
    assert sent.get_header("X-nex-tenant-id") == fixture.TENANT
    assert sent.get_header("X-nex-company-id") == fixture.COMPANY_ID
    assert sent.get_header("X-nex-subject-id") == SUBJECT
    assert sent.get_header("X-nex-correlation-id") == CORRELATION
    assert sent.get_header("Authorization") == "Bearer signed-token"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"eos_base_url": "file:///tmp/eos", "service_token": "token"},
        {"eos_base_url": "http://eos.local", "service_token": ""},
        {
            "eos_base_url": "http://eos.local",
            "service_token": "token",
            "timeout_seconds": 0,
        },
    ],
)
def test_http_transport_configuration_fails_closed(kwargs) -> None:
    with pytest.raises(ProjectPnlConsumerError) as caught:
        HttpProjectPnlProviderTransport(**kwargs)
    assert caught.value.status_code == 400


def test_http_transport_maps_problem_and_unavailability(monkeypatch) -> None:
    transport = HttpProjectPnlProviderTransport(
        eos_base_url="http://eos.local", service_token="token"
    )
    request = build_project_pnl_request(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
    )
    problem = json.dumps(
        {"error_code": "PROJECT_PNL_QUERY_NOT_FOUND", "retryable": False}
    ).encode()
    monkeypatch.setattr(
        consumer_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError("http://eos", 404, "missing", {}, BytesIO(problem))
        ),
    )
    with pytest.raises(ProjectPnlConsumerError) as rejected:
        transport.send(request)
    assert rejected.value.error_code == "PROJECT_PNL_QUERY_NOT_FOUND"
    assert rejected.value.status_code == 404

    monkeypatch.setattr(
        consumer_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(ProjectPnlConsumerError) as unavailable:
        transport.send(request)
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


@pytest.mark.parametrize("problem", [b"not-json", b"[]"])
def test_http_transport_uses_default_error_for_malformed_problem(
    monkeypatch, problem
) -> None:
    transport = HttpProjectPnlProviderTransport(
        eos_base_url="http://eos.local", service_token="token"
    )
    request = build_project_pnl_request(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
    )
    monkeypatch.setattr(
        consumer_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError("http://eos", 500, "failed", {}, BytesIO(problem))
        ),
    )
    with pytest.raises(ProjectPnlConsumerError) as caught:
        transport.send(request)
    assert caught.value.error_code == "EOS_PROJECT_PNL_REJECTED"
    assert caught.value.retryable is True


@pytest.mark.parametrize("payload", [b"not-json", b"[]"])
def test_http_transport_rejects_malformed_json(monkeypatch, payload) -> None:
    class RawResponse(Response):
        def __init__(self):
            self._payload = payload

    monkeypatch.setattr(
        consumer_module, "urlopen", lambda *_args, **_kwargs: RawResponse()
    )
    transport = HttpProjectPnlProviderTransport(
        eos_base_url="http://eos.local", service_token="token"
    )
    request = build_project_pnl_request(
        tenant_id=fixture.TENANT,
        company_id=fixture.COMPANY_ID,
        project_id=fixture.PROJECT_ID,
        period_id=fixture.PERIOD_ID,
        subject_id=SUBJECT,
        correlation_id=CORRELATION,
    )
    with pytest.raises(ProjectPnlConsumerError) as caught:
        transport.send(request)
    assert caught.value.status_code == 502
