from __future__ import annotations

import io
import json
from collections.abc import Mapping
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from mybee_ax.integrations import (
    PROJECT_PNL_REFRESH_OPERATION,
    PROJECT_PNL_REFRESH_PATH,
    PROJECT_PNL_REFRESH_SCHEMA,
    HttpProjectPnlRefreshProviderTransport,
    NexProjectPnlRefreshClient,
    ProjectPnlRefreshConsumerError,
    ProjectPnlRefreshProviderRequest,
    admit_project_pnl_refresh_result,
    build_project_pnl_refresh_request,
)
from nex_ae_api.project_pnl_refresh_runtime import (
    PROJECT_PNL_REFRESH_RUNTIME_SCHEMA,
    InstalledProjectPnlRefresh,
    InstalledProjectPnlRefreshError,
    build_installed_project_pnl_refresh,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "VO00"
COMPANY = "73000000-0000-4000-8000-000000000001"
BATCH = "73000000-0000-4000-8000-000000000005"
PERIOD = "73000000-0000-4000-8000-000000000002"
PROJECT_A = "73000000-0000-4000-8000-000000000010"
PROJECT_B = "73000000-0000-4000-8000-000000000011"
PROJECTION_A = "73000000-0000-4000-8000-000000000030"
PROJECTION_B = "73000000-0000-4000-8000-000000000031"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _request() -> ProjectPnlRefreshProviderRequest:
    return build_project_pnl_refresh_request(
        tenant_id=TENANT,
        company_id=COMPANY,
        batch_id=BATCH,
        correlation_id="corr-refresh-001",
    )


def _response(*, disposition: str = "CREATED") -> dict:
    projections = [
        {
            "project_id": PROJECT_A,
            "project_code": "VO00D260001",
            "projection_id": PROJECTION_A,
            "projection_version": 1,
            "projection_hash": HASH_B,
            "reconciliation_status": "VERIFIED",
            "freshness_status": "CURRENT",
        },
        {
            "project_id": PROJECT_B,
            "project_code": "VO00D260002",
            "projection_id": PROJECTION_B,
            "projection_version": 1,
            "projection_hash": HASH_C,
            "reconciliation_status": "VERIFIED",
            "freshness_status": "CURRENT",
        },
    ]
    semantics = {
        "schema_version": PROJECT_PNL_REFRESH_SCHEMA,
        "operation": PROJECT_PNL_REFRESH_OPERATION,
        "tenant_id": TENANT,
        "company_id": COMPANY,
        "batch_id": BATCH,
        "period_id": PERIOD,
        "allocation_reconciliation_hash": HASH_A,
        "projections": projections,
    }
    return {
        **semantics,
        "disposition": disposition,
        "refresh_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-PROJECT-PNL-REFRESH-V1", **semantics}
        ),
    }


class _Transport:
    def __init__(self, value: Mapping[str, object]) -> None:
        self.value = value
        self.requests: list[ProjectPnlRefreshProviderRequest] = []

    def send(self, request: ProjectPnlRefreshProviderRequest):
        self.requests.append(request)
        return self.value


class _Response:
    def __init__(self, value: object) -> None:
        self.payload = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


def test_request_client_and_runtime_admit_exact_authority(monkeypatch):
    transport = _Transport(_response())
    client = NexProjectPnlRefreshClient(transport)
    result = client.refresh(
        tenant_id=TENANT,
        company_id=COMPANY,
        batch_id=BATCH,
        correlation_id="corr-refresh-001",
    )
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.path == PROJECT_PNL_REFRESH_PATH.format(batch_id=BATCH)
    assert request.operation_id == PROJECT_PNL_REFRESH_OPERATION
    assert result["disposition"] == "CREATED"
    assert isinstance(result["projections"], tuple)
    with pytest.raises(TypeError):
        result["disposition"] = "EXACT_REPLAY"

    runtime = InstalledProjectPnlRefresh(client=client, timeout_seconds=19.0)
    replay = runtime.refresh(
        tenant_id=TENANT,
        company_id=COMPANY,
        batch_id=BATCH,
        correlation_id="corr-refresh-002",
    )
    readiness = runtime.readiness()
    assert replay["refresh_hash"] == result["refresh_hash"]
    assert readiness["schema_version"] == PROJECT_PNL_REFRESH_RUNTIME_SCHEMA
    assert readiness["status"] == "READY"
    assert readiness["business_defaults_included"] is False
    assert readiness["secret_included"] is False
    assert readiness["readiness_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "drift.v1"),
        ("operation", "FINANCE.PROJECT_PNL.GET"),
        ("tenant_id", "OTHER"),
        ("company_id", "73000000-0000-4000-8000-000000000099"),
        ("batch_id", "73000000-0000-4000-8000-000000000099"),
        ("period_id", "not-a-uuid"),
        ("allocation_reconciliation_hash", "bad"),
        ("disposition", "UPDATED"),
        ("refresh_hash", HASH_A),
    ],
)
def test_response_rejects_header_identity_and_hash_drift(field, value):
    response = _response()
    response[field] = value
    with pytest.raises(ProjectPnlRefreshConsumerError) as rejected:
        admit_project_pnl_refresh_result(response, request=_request())
    assert rejected.value.error_code == "MYBEE_PNL_REFRESH_CONTRACT_DRIFT"
    assert rejected.value.status_code == 502


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "not-a-uuid"),
        ("project_code", "INVALID"),
        ("projection_id", "not-a-uuid"),
        ("projection_version", 0),
        ("projection_version", True),
        ("projection_version", "one"),
        ("projection_hash", "bad"),
        ("reconciliation_status", "PARTIAL"),
        ("freshness_status", "STALE"),
    ],
)
def test_response_rejects_projection_drift(field, value):
    response = _response()
    response["projections"][0][field] = value
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(response, request=_request())


def test_response_rejects_shape_empty_duplicate_and_ordering_drift():
    extra = _response()
    extra["unexpected"] = True
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(extra, request=_request())

    empty = _response()
    empty["projections"] = []
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(empty, request=_request())

    non_array = _response()
    non_array["projections"] = {}
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(non_array, request=_request())

    malformed = _response()
    malformed["projections"][0].pop("freshness_status")
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(malformed, request=_request())

    duplicate = _response()
    duplicate["projections"][1]["project_id"] = PROJECT_A
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(duplicate, request=_request())

    duplicate_projection = _response()
    duplicate_projection["projections"][1]["projection_id"] = PROJECTION_A
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(duplicate_projection, request=_request())

    reversed_result = _response()
    reversed_result["projections"].reverse()
    with pytest.raises(ProjectPnlRefreshConsumerError):
        admit_project_pnl_refresh_result(reversed_result, request=_request())


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        ({"tenant_id": "bad tenant"}, "MYBEE_PNL_REFRESH_ARGUMENT_INVALID"),
        ({"company_id": "bad"}, "MYBEE_PNL_REFRESH_ARGUMENT_INVALID"),
        ({"batch_id": "bad"}, "MYBEE_PNL_REFRESH_ARGUMENT_INVALID"),
        ({"correlation_id": "bad correlation"}, "MYBEE_PNL_REFRESH_ARGUMENT_INVALID"),
    ],
)
def test_request_rejects_invalid_selectors(kwargs, error_code):
    values = {
        "tenant_id": TENANT,
        "company_id": COMPANY,
        "batch_id": BATCH,
        "correlation_id": "corr-refresh-001",
    }
    values.update(kwargs)
    with pytest.raises(ProjectPnlRefreshConsumerError) as rejected:
        build_project_pnl_refresh_request(**values)
    assert rejected.value.error_code == error_code
    assert rejected.value.status_code == 400


def test_http_transport_sends_header_only_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(_response(disposition="EXACT_REPLAY"))

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_project_pnl_refresh_client.urlopen", fake_urlopen
    )
    transport = HttpProjectPnlRefreshProviderTransport(
        eos_base_url="https://eos.internal/base",
        service_token="secret-token",
        timeout_seconds=21,
    )
    result = NexProjectPnlRefreshClient(transport).refresh_request(_request())
    outgoing = captured["request"]
    assert outgoing.full_url.endswith(PROJECT_PNL_REFRESH_PATH.format(batch_id=BATCH))
    assert outgoing.method == "POST"
    assert outgoing.data is None
    assert outgoing.get_header("Authorization") == "Bearer secret-token"
    assert outgoing.get_header("X-nex-tenant-id") == TENANT
    assert captured["timeout"] == 21
    assert result["disposition"] == "EXACT_REPLAY"


@pytest.mark.parametrize(
    "constructor",
    [
        {"eos_base_url": "file:///tmp/eos", "service_token": "x"},
        {"eos_base_url": "https://eos.internal", "service_token": ""},
        {
            "eos_base_url": "https://eos.internal",
            "service_token": "x",
            "timeout_seconds": 0,
        },
    ],
)
def test_http_transport_rejects_invalid_configuration(constructor):
    with pytest.raises(ProjectPnlRefreshConsumerError) as rejected:
        HttpProjectPnlRefreshProviderTransport(**constructor)
    assert rejected.value.status_code == 400


def test_http_transport_maps_rejection_unavailable_and_malformed_json(monkeypatch):
    transport = HttpProjectPnlRefreshProviderTransport(
        eos_base_url="https://eos.internal",
        service_token="token",
    )

    def rejected(*_args, **_kwargs):
        raise HTTPError(
            "https://eos.internal",
            409,
            "Conflict",
            {},
            io.BytesIO(json.dumps({"error_code": "BATCH_NOT_VERIFIED"}).encode()),
        )

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_project_pnl_refresh_client.urlopen", rejected
    )
    with pytest.raises(ProjectPnlRefreshConsumerError) as conflict:
        transport.send(_request())
    assert conflict.value.error_code == "BATCH_NOT_VERIFIED"
    assert conflict.value.retryable is False

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_project_pnl_refresh_client.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(ProjectPnlRefreshConsumerError) as unavailable:
        transport.send(_request())
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_project_pnl_refresh_client.urlopen",
        lambda *_args, **_kwargs: _Response(["not", "object"]),
    )
    with pytest.raises(ProjectPnlRefreshConsumerError):
        transport.send(_request())

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_project_pnl_refresh_client.urlopen",
        lambda *_args, **_kwargs: SimpleNamespace(
            __enter__=lambda self: self,
            __exit__=lambda *_args: False,
            read=lambda: b"not-json",
        ),
    )
    with pytest.raises((ProjectPnlRefreshConsumerError, TypeError)):
        transport.send(_request())


def test_installed_runtime_builds_with_signed_token_resolution(monkeypatch):
    monkeypatch.setattr(
        "nex_ae_api.project_pnl_refresh_runtime.resolve_ae_outbound_service_token",
        lambda *_args, **_kwargs: "resolved-token",
    )
    runtime = build_installed_project_pnl_refresh(
        {
            "NEX_EOS_BASE_URL": "https://eos.internal/",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "29",
        }
    )
    assert runtime.timeout_seconds == 29
    assert runtime.readiness()["operation"] == PROJECT_PNL_REFRESH_OPERATION


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"NEX_EOS_BASE_URL": "file:///tmp/eos"},
        {
            "NEX_EOS_BASE_URL": "https://eos.internal",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "slow",
        },
        {
            "NEX_EOS_BASE_URL": "https://eos.internal",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "0",
        },
        {
            "NEX_EOS_BASE_URL": "https://eos.internal",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "121",
        },
    ],
)
def test_installed_runtime_fails_closed_for_invalid_configuration(
    monkeypatch, environment
):
    monkeypatch.setattr(
        "nex_ae_api.project_pnl_refresh_runtime.resolve_ae_outbound_service_token",
        lambda *_args, **_kwargs: "token",
    )
    with pytest.raises(InstalledProjectPnlRefreshError):
        build_installed_project_pnl_refresh(environment)


def test_installed_runtime_wraps_token_resolution_failure(monkeypatch):
    monkeypatch.setattr(
        "nex_ae_api.project_pnl_refresh_runtime.resolve_ae_outbound_service_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    with pytest.raises(InstalledProjectPnlRefreshError):
        build_installed_project_pnl_refresh(
            {"NEX_EOS_BASE_URL": "https://eos.internal"}
        )
