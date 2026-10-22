from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import httpx
import pytest
from nex_ae_api.nsl_eos_post_write_verification import (
    EOS_VOUCHER_VERIFICATION_PATH,
    EosPostWriteVerificationError,
    EosVoucherVerificationResponse,
    HttpEosPostWriteVerificationAdapter,
    build_default_eos_post_write_verification_adapter,
    map_eos_voucher_verification_response,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

HASH = "sha256:" + "a" * 64
PAYLOAD_HASH = "sha256:" + "b" * 64
REQUEST_HASH = "sha256:" + "c" * 64
OPERATION_ID = "86000000-0000-4000-8000-000000000061"
VOUCHER_ID = "84000000-0000-4000-8000-000000000061"
PROJECT_ID = "82000000-0000-4000-8000-000000000061"
IDEMPOTENCY_KEY = "idem:sha256:" + "d" * 64
NOW = datetime(2026, 10, 22, 13, tzinfo=UTC)


@dataclass(frozen=True)
class WriteOutcomeIdentity:
    tenant_id: str
    business_operation_id: str
    invocation_id: str
    node_id: str
    tool_id: str
    idempotency_key: str
    payload_hash: str
    approval_request_id: str
    write_intent_hash: str


@dataclass(frozen=True)
class VerificationRequest:
    identity: object
    verification_tool_id: str
    business_reference: str
    provider_transaction_id: str | None
    reference_schema: object = None
    consistency_hint: str | None = "READ_AFTER_WRITE_STRONG"
    request_hash: str = REQUEST_HASH


@dataclass(frozen=True)
class VerificationObservation:
    request_hash: str
    business_reference: str
    matched: bool
    evidence_ref: str
    observed_at: datetime
    reason_code: str | None = None


@runtime_checkable
class PostWriteVerificationPort(Protocol):
    async def read(self, request: VerificationRequest) -> VerificationObservation: ...


def _public_api() -> NslV02PublicApiAdapter:
    return NslV02PublicApiAdapter(
        approval_request=object,
        approval_evidence=object,
        approval_suspension_coordinator=object,
        approval_resume_coordinator=object,
        resume_token=object,
        checkpoint_port=object,
        resume_checkpoint_port=object,
        idempotency_coordinator=object,
        idempotency_evidence_port=object,
        idempotency_evidence_record=object,
        idempotency_reservation=object,
        idempotency_disposition=object,
        write_evidence_port=object,
        write_attempt_record=object,
        write_requested_receipt=object,
        write_call_request=object,
        write_execution_port=object,
        write_outcome_identity=WriteOutcomeIdentity,
        write_result_envelope=object,
        write_committed=object,
        write_not_committed=object,
        write_commit_unknown=object,
        post_write_verification_port=PostWriteVerificationPort,
        verification_request=VerificationRequest,
        verification_observation=VerificationObservation,
        runtime_policy_port=object,
        write_policy_request=object,
        policy_decision=object,
        policy_effect=object,
        runtime_preflight_validator=object,
        release_admission_hash=HASH,
        api_contract_hash=HASH,
    )


def _identity(**changes: object) -> WriteOutcomeIdentity:
    values = {
        "tenant_id": "tenant-p8-s61",
        "business_operation_id": OPERATION_ID,
        "invocation_id": "invocation-p8-s61",
        "node_id": "write-voucher-draft",
        "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "idempotency_key": IDEMPOTENCY_KEY,
        "payload_hash": PAYLOAD_HASH,
        "approval_request_id": "approval-request-p8-s61",
        "write_intent_hash": "sha256:" + "e" * 64,
    }
    values.update(changes)
    return WriteOutcomeIdentity(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> VerificationRequest:
    values = {
        "identity": _identity(),
        "verification_tool_id": "FINANCE.GET_VOUCHER_DRAFT",
        "business_reference": f"eos.voucher_draft:{VOUCHER_ID}",
        "provider_transaction_id": OPERATION_ID,
        "reference_schema": object(),
        "consistency_hint": "READ_AFTER_WRITE_STRONG",
        "request_hash": REQUEST_HASH,
    }
    values.update(changes)
    return VerificationRequest(**values)  # type: ignore[arg-type]


def _projection(**changes: object) -> dict[str, object]:
    values = {
        "schema_version": "eos_voucher_verification.v1",
        "tenant_id": "tenant-p8-s61",
        "voucher_ref": {"type": "eos.voucher_draft", "id": VOUCHER_ID},
        "business_operation_id": OPERATION_ID,
        "operation": "FINANCE.CREATE_VOUCHER_DRAFT",
        "idempotency_key": IDEMPOTENCY_KEY,
        "business_transaction_ref": {
            "type": "eos.business_operation",
            "id": OPERATION_ID,
        },
        "payload_hash": PAYLOAD_HASH,
        "commit_state": "COMMITTED",
        "voucher_state": "DRAFT",
        "voucher_version": 1,
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "line_count": 2,
        "attachment_count": 0,
        "balance": "0.00",
        "stable_business_state_hash": "sha256:" + "f" * 64,
        "last_observed_at": "2026-10-22T13:00:00Z",
    }
    values.update(changes)
    return values


def _adapter(
    transport: httpx.AsyncBaseTransport,
) -> HttpEosPostWriteVerificationAdapter:
    return HttpEosPostWriteVerificationAdapter(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-token",
        transport=transport,
        clock=lambda: NOW,
    )


def _read(adapter: HttpEosPostWriteVerificationAdapter, request=None):
    return asyncio.run(adapter.read(request or _request()))


def test_verified_projection_maps_to_admitted_observation_and_get_only() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
        )
        return httpx.Response(200, json=_projection(), request=request)

    adapter = _adapter(httpx.MockTransport(handler))
    result = _read(adapter)

    assert isinstance(adapter, PostWriteVerificationPort)
    assert isinstance(result, VerificationObservation)
    assert result.matched is True
    assert result.reason_code is None
    assert result.request_hash == REQUEST_HASH
    assert result.business_reference == f"eos.voucher_draft:{VOUCHER_ID}"
    assert result.observed_at == NOW
    assert result.evidence_ref == (
        f"eos.voucher_verification:{OPERATION_ID}:sha256:" + "f" * 64
    )
    assert observed["method"] == "GET"
    assert observed["url"] == (
        f"http://eos.test{EOS_VOUCHER_VERIFICATION_PATH}/{VOUCHER_ID}/verification"
        f"?business_operation_id={OPERATION_ID}"
    )
    headers = observed["headers"]
    assert headers["authorization"] == "Bearer signed-token"
    assert headers["x-nex-tenant-id"] == "tenant-p8-s61"
    assert headers["cache-control"] == "no-store, max-age=0"
    assert headers["pragma"] == "no-cache"


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (404, "EOS_VOUCHER_VERIFICATION_NOT_FOUND"),
        (409, "EOS_VOUCHER_VERIFICATION_BINDING_INVALID"),
    ],
)
def test_authoritative_failure_maps_to_failed_observation(
    status: int,
    reason: str,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            json={"status": status, "error_code": reason},
            request=request,
        )
    )

    result = _read(_adapter(transport))

    assert isinstance(result, VerificationObservation)
    assert result.matched is False
    assert result.reason_code == reason
    assert result.observed_at == NOW
    assert result.evidence_ref == (
        f"eos.voucher_verification_failure:{OPERATION_ID}:{reason}"
    )


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, {"status": 401, "error_code": "SERVICE_TOKEN_REQUIRED"}),
        (403, {"status": 403, "error_code": "SERVICE_TOKEN_FORBIDDEN"}),
        (404, {"status": 404, "error_code": "OTHER_NOT_FOUND"}),
        (
            409,
            {"status": 400, "error_code": "EOS_VOUCHER_VERIFICATION_BINDING_INVALID"},
        ),
        (422, {"status": 422, "error_code": "EOS_VOUCHER_VERIFICATION_INVALID"}),
        (503, {"status": 503, "error_code": "EOS_VOUCHER_VERIFICATION_UNAVAILABLE"}),
    ],
)
def test_non_authoritative_http_result_raises_dependency_error(
    status: int,
    body: dict[str, object],
) -> None:
    response = EosVoucherVerificationResponse(status, body)

    with pytest.raises(EosPostWriteVerificationError) as error:
        map_eos_voucher_verification_response(
            response,
            _request(),
            public_api=_public_api(),
            observed_at=NOW,
        )

    assert error.value.error_code == "ae.nsl_eos_verification.unavailable"
    assert error.value.status_code == status


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra="field"),
        lambda value: value.pop("line_count"),
        lambda value: value.update(tenant_id="tenant-other"),
        lambda value: value.update(business_operation_id=str(VOUCHER_ID)),
        lambda value: value.update(operation="FINANCE.OTHER_WRITE"),
        lambda value: value.update(idempotency_key="idem:other"),
        lambda value: value.update(payload_hash="sha256:" + "0" * 64),
        lambda value: value.update(commit_state="PENDING"),
        lambda value: value.update(voucher_state="POSTED"),
        lambda value: value.update(balance="1.00"),
        lambda value: value.update(
            voucher_ref={"type": "eos.voucher_draft", "id": PROJECT_ID}
        ),
        lambda value: value.update(
            voucher_ref={"type": "eos.voucher_draft", "id": "bad"}
        ),
        lambda value: value.update(
            business_transaction_ref={
                "type": "eos.business_operation",
                "id": VOUCHER_ID,
            }
        ),
        lambda value: value.update(project_ref={"type": "wrong", "id": PROJECT_ID}),
        lambda value: value.update(project_ref={"type": "eos.project", "id": "bad"}),
        lambda value: value.update(voucher_version=0),
        lambda value: value.update(line_count=1),
        lambda value: value.update(attachment_count=-1),
        lambda value: value.update(stable_business_state_hash="bad"),
        lambda value: value.update(last_observed_at=42),
        lambda value: value.update(last_observed_at="not-a-time"),
        lambda value: value.update(last_observed_at="2026-10-22T13:00:00+09:00"),
    ],
)
def test_untrustworthy_success_response_fails_closed(mutation) -> None:
    payload = _projection()
    mutation(payload)

    with pytest.raises(EosPostWriteVerificationError):
        map_eos_voucher_verification_response(
            EosVoucherVerificationResponse(200, payload),
            _request(),
            public_api=_public_api(),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "candidate",
    [
        object(),
        _request(identity=object()),
        _request(identity=_identity(tool_id="FINANCE.OTHER_WRITE")),
        _request(verification_tool_id="FINANCE.GET_VOUCHER"),
        _request(consistency_hint="EVENTUAL"),
        _request(provider_transaction_id=str(VOUCHER_ID)),
        _request(business_reference="voucher:bad"),
        _request(business_reference="eos.voucher_draft:bad"),
        _request(identity=_identity(tenant_id="bad value")),
        _request(identity=_identity(invocation_id="bad value")),
        _request(identity=_identity(business_operation_id="bad")),
        _request(identity=_identity(payload_hash="bad")),
        _request(identity=_identity(idempotency_key="bad value")),
        _request(request_hash="bad"),
    ],
)
def test_invalid_verification_request_fails_before_dispatch(candidate: object) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(EosPostWriteVerificationError):
        _read(_adapter(httpx.MockTransport(handler)), candidate)

    assert calls == 0


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (httpx.ReadTimeout("slow"), TimeoutError),
        (httpx.ConnectError("offline"), ConnectionError),
        (httpx.UnsupportedProtocol("bad"), EosPostWriteVerificationError),
    ],
)
def test_transport_failure_is_typed_and_never_retried(
    failure: Exception,
    error: type[Exception],
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(error):
        _read(_adapter(httpx.MockTransport(handler)))

    assert calls == 1


@pytest.mark.parametrize("body", ["not-json", ["not", "an", "object"]])
def test_invalid_http_body_fails_closed(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(200, text=body, request=request)
        return httpx.Response(200, json=body, request=request)

    with pytest.raises(EosPostWriteVerificationError):
        _read(_adapter(httpx.MockTransport(handler)))


def test_service_token_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    monkeypatch.delenv("NEX_AE_TO_EOS_SERVICE_TOKEN", raising=False)
    adapter = HttpEosPostWriteVerificationAdapter(
        _public_api(),
        "http://eos.test",
    )

    with pytest.raises(EosPostWriteVerificationError, match="authentication"):
        _read(adapter)


def test_failure_observation_requires_utc_clock() -> None:
    response = EosVoucherVerificationResponse(
        404,
        {
            "status": 404,
            "error_code": "EOS_VOUCHER_VERIFICATION_NOT_FOUND",
        },
    )
    with pytest.raises(EosPostWriteVerificationError, match="UTC"):
        map_eos_voucher_verification_response(
            response,
            _request(),
            public_api=_public_api(),
            observed_at=NOW.replace(tzinfo=None),
        )
    with pytest.raises(EosPostWriteVerificationError, match="UTC"):
        map_eos_voucher_verification_response(
            response,
            _request(),
            public_api=_public_api(),
            observed_at=NOW.astimezone(timezone(timedelta(hours=9))),
        )


def test_default_clock_produces_utc_failure_observation() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            404,
            json={
                "status": 404,
                "error_code": "EOS_VOUCHER_VERIFICATION_NOT_FOUND",
            },
            request=request,
        )
    )
    adapter = HttpEosPostWriteVerificationAdapter(
        _public_api(),
        "http://eos.test",
        "token",
        transport=transport,
    )

    result = _read(adapter)

    assert result.observed_at.tzinfo is UTC


def test_mapper_rejects_non_response_value() -> None:
    with pytest.raises(TypeError, match="EosVoucherVerificationResponse"):
        map_eos_voucher_verification_response(
            object(),  # type: ignore[arg-type]
            _request(),
            public_api=_public_api(),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "base_url",
    ["", " eos.test", "ftp://eos.test", "http://user:secret@eos.test"],
)
def test_adapter_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        HttpEosPostWriteVerificationAdapter(_public_api(), base_url)


@pytest.mark.parametrize("timeout", [True, 0, -1, "15"])
def test_adapter_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError):
        HttpEosPostWriteVerificationAdapter(
            _public_api(),
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_adapter_rejects_noncallable_clock() -> None:
    with pytest.raises(TypeError, match="clock"):
        HttpEosPostWriteVerificationAdapter(
            _public_api(),
            clock=object(),  # type: ignore[arg-type]
        )


def test_default_builder_reads_verification_configuration() -> None:
    adapter = build_default_eos_post_write_verification_adapter(
        public_api=_public_api(),
        environ={
            "NEX_EOS_BASE_URL": "https://eos.internal",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "token-p8-s61",
            "NEX_AE_EOS_VERIFICATION_TIMEOUT_SECONDS": "12.5",
        },
    )
    assert adapter.base_url == "https://eos.internal"
    assert adapter.service_token == "token-p8-s61"
    assert adapter.timeout_seconds == 12.5

    with pytest.raises(ValueError, match="must be numeric"):
        build_default_eos_post_write_verification_adapter(
            public_api=_public_api(),
            environ={"NEX_AE_EOS_VERIFICATION_TIMEOUT_SECONDS": "slow"},
        )


def test_adapter_normalizes_url_parser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_value: object):
        raise ValueError("private parser detail")

    monkeypatch.setattr(httpx, "URL", fail)

    with pytest.raises(ValueError, match="bounded HTTP URL"):
        HttpEosPostWriteVerificationAdapter(_public_api(), "http://eos.test")


def test_raw_query_exposes_typed_response() -> None:
    adapter = _adapter(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_projection(), request=request)
        )
    )

    response = asyncio.run(adapter.query_raw(_request()))

    assert isinstance(response, EosVoucherVerificationResponse)
    assert response.status_code == 200
    assert response.payload["stable_business_state_hash"] == "sha256:" + "f" * 64
