from __future__ import annotations

from typing import Any

import httpx
import pytest

import nex_runtime.subject_resolver as subject_resolver
from nex_runtime import (
    OA_SUBJECT_RESOLVER_SCHEMA_VERSION,
    HttpSubjectRegistryResolver,
    SubjectRegistryResolverError,
    build_default_subject_registry_resolver,
    build_subject_resolution_result,
    normalize_ownership_ref_for_resolution,
    required_resolver_subject_ref,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def ownership_ref(
    *,
    tenant_id: str = "tenant-a",
    owner_id: str = "user-a",
    uploaded_by_id: str = "uploader-a",
) -> dict[str, Any]:
    return {
        "ownership_schema_version": "cx_source_ownership_ref.v1",
        "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
        "owner_subject_ref": {"type": "oa.user", "id": owner_id},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": uploaded_by_id},
        "legacy": {"tenant_id": tenant_id, "owner_user_id": owner_id},
        "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
    }


def subject_snapshot(
    *,
    tenant_id: str = "tenant-a",
    subject_id: str = "user-a",
) -> dict[str, Any]:
    return {
        "snapshot_schema_version": "oa_subject_registry_snapshot.v1",
        "service_id": "nex-oa",
        "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
        "subject_ref": {"type": "oa.user", "id": subject_id},
        "subject": {"status": "ACTIVE"},
    }


def tenant_snapshot(*, tenant_id: str = "tenant-a") -> dict[str, Any]:
    return {
        "snapshot_schema_version": "oa_subject_registry_snapshot.v1",
        "service_id": "nex-oa",
        "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
        "subject_ref": None,
        "subject": None,
    }


def test_normalize_ownership_ref_for_resolution_defaults_uploaded_by_to_owner() -> None:
    normalized = normalize_ownership_ref_for_resolution(
        {
            "tenant_ref": {"type": "oa.tenant", "id": " tenant-a "},
            "owner_subject_ref": {"type": "oa.user", "id": " user-a "},
        }
    )

    assert normalized == {
        "ownership_schema_version": "cx_source_ownership_ref.v1",
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": "user-a"},
        "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
    }


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "object"],
        {"email": "private@example.test"},
        {"ownership_schema_version": "cx_source_ownership_ref.v0"},
        {"compatibility_mode": "raw_identity"},
        {
            "tenant_ref": {"type": "cx.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a", "email": "x"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        {
            "tenant_ref": {"type": "oa.tenant", "id": ""},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        },
    ],
)
def test_normalize_ownership_ref_for_resolution_rejects_invalid_shapes(
    payload: object,
) -> None:
    with pytest.raises(SubjectRegistryResolverError) as exc:
        normalize_ownership_ref_for_resolution(payload)  # type: ignore[arg-type]

    assert exc.value.status_code == 422
    assert exc.value.error_code == "oa.subject_resolver_owner_ref_invalid"


def test_required_resolver_subject_ref_rejects_non_object() -> None:
    with pytest.raises(SubjectRegistryResolverError) as exc:
        required_resolver_subject_ref(
            "not-object",
            field_name="tenant_ref",
            expected_type="oa.tenant",
        )

    assert exc.value.detail == "tenant_ref must be an object."


def test_http_subject_resolver_verifies_tenant_owner_and_uploaded_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if url.endswith("/tenants/tenant-a"):
            return httpx.Response(200, json=tenant_snapshot())
        if url.endswith("/subjects/user-a"):
            return httpx.Response(200, json=subject_snapshot(subject_id="user-a"))
        if url.endswith("/subjects/uploader-a"):
            return httpx.Response(200, json=subject_snapshot(subject_id="uploader-a"))
        return httpx.Response(404, json={"error_code": "oa.subject_not_found"})

    monkeypatch.setattr(subject_resolver.httpx, "request", fake_request)
    resolver = HttpSubjectRegistryResolver(
        base_url="http://oa.local/",
        caller_service_id="nex-cx",
        service_token="fixed-token",
    )

    result = resolver.resolve_ownership_ref(
        ownership_ref(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert result["resolver_schema_version"] == OA_SUBJECT_RESOLVER_SCHEMA_VERSION
    assert result["resolver_mode"] == "http"
    assert result["action"] == "verify"
    assert result["owner_snapshot_ref"]["subject_ref"]["id"] == "user-a"
    assert result["uploaded_by_snapshot_ref"]["subject_ref"]["id"] == "uploader-a"
    assert [call["method"] for call in calls] == ["GET", "GET", "GET"]
    assert calls[0]["kwargs"]["headers"]["Authorization"] == "Bearer fixed-token"
    assert calls[0]["kwargs"]["headers"]["X-Service-ID"] == "nex-cx"


def test_http_subject_resolver_ensure_deduplicates_uploaded_by_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, "json": kwargs.get("json")})
        return httpx.Response(200, json=subject_snapshot())

    monkeypatch.setattr(subject_resolver.httpx, "request", fake_request)
    resolver = HttpSubjectRegistryResolver(caller_service_id="nex-ae-api")

    result = resolver.resolve_ownership_ref(
        ownership_ref(uploaded_by_id="user-a"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        ensure=True,
    )

    assert result["action"] == "ensure"
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {"tenant_id": "tenant-a", "subject_id": "user-a"}


def test_http_subject_resolver_ensure_creates_distinct_uploaded_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "json": kwargs.get("json")})
        subject_id = kwargs["json"]["subject_id"]
        return httpx.Response(200, json=subject_snapshot(subject_id=subject_id))

    monkeypatch.setattr(subject_resolver.httpx, "request", fake_request)

    HttpSubjectRegistryResolver(caller_service_id="nex-ae-api").resolve_ownership_ref(
        ownership_ref(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        ensure=True,
    )

    assert [call["json"]["subject_id"] for call in calls] == ["user-a", "uploader-a"]


def test_http_subject_resolver_quotes_path_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        if "/tenants/" in url and "/subjects/" not in url:
            return httpx.Response(200, json=tenant_snapshot(tenant_id="tenant:a"))
        return httpx.Response(
            200,
            json=subject_snapshot(tenant_id="tenant:a", subject_id="user:a"),
        )

    monkeypatch.setattr(subject_resolver.httpx, "request", fake_request)

    HttpSubjectRegistryResolver().resolve_ownership_ref(
        ownership_ref(tenant_id="tenant:a", owner_id="user:a", uploaded_by_id="user:a"),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert urls[0].endswith("/tenants/tenant%3Aa")
    assert urls[1].endswith("/tenants/tenant%3Aa/subjects/user%3Aa")


def test_http_subject_resolver_maps_problem_and_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def problem_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error_code": "oa.subject_not_found",
                "detail": "missing",
                "retryable": False,
            },
        )

    monkeypatch.setattr(subject_resolver.httpx, "request", problem_request)
    resolver = HttpSubjectRegistryResolver()

    with pytest.raises(SubjectRegistryResolverError) as problem:
        resolver.resolve_ownership_ref(
            ownership_ref(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert problem.value.status_code == 404
    assert problem.value.error_code == "oa.subject_not_found"
    assert problem.value.retryable is False

    def down_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(subject_resolver.httpx, "request", down_request)
    with pytest.raises(SubjectRegistryResolverError) as unavailable:
        resolver.resolve_ownership_ref(
            ownership_ref(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["not", "object"]),
    ],
)
def test_http_subject_resolver_rejects_invalid_json_responses(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
) -> None:
    monkeypatch.setattr(
        subject_resolver.httpx,
        "request",
        lambda method, url, **kwargs: response,
    )

    with pytest.raises(SubjectRegistryResolverError) as exc:
        HttpSubjectRegistryResolver().resolve_ownership_ref(
            ownership_ref(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "oa.subject_resolver_response_invalid"


def test_build_default_subject_registry_resolver_uses_environment() -> None:
    resolver = build_default_subject_registry_resolver(
        caller_service_id="nex-ae-api",
        environ={
            "NEX_OA_BASE_URL": "http://oa.internal",
            "NEX_AE_TO_OA_SERVICE_TOKEN": "ae-token",
            "NEX_OA_SUBJECT_RESOLVER_TIMEOUT_SECONDS": "2.5",
        },
    )

    assert resolver.base_url == "http://oa.internal"
    assert resolver.service_token == "ae-token"
    assert resolver.timeout_seconds == 2.5


@pytest.mark.parametrize(
    ("caller_service_id", "timeout"),
    [
        ("unknown-service", "2"),
        ("nex-cx", "0"),
        ("nex-cx", "not-a-number"),
    ],
)
def test_build_default_subject_registry_resolver_rejects_invalid_config(
    caller_service_id: str,
    timeout: str,
) -> None:
    with pytest.raises(SubjectRegistryResolverError):
        build_default_subject_registry_resolver(
            caller_service_id=caller_service_id,
            environ={"NEX_OA_SUBJECT_RESOLVER_TIMEOUT_SECONDS": timeout},
        )


def test_subject_resolution_result_handles_missing_subject_snapshot() -> None:
    result = build_subject_resolution_result(
        normalize_ownership_ref_for_resolution(ownership_ref(uploaded_by_id="user-a")),
        resolver_mode="test",
        ensure=False,
        owner_snapshot=subject_snapshot(),
        uploaded_by_snapshot={
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "subject_ref": {"type": "oa.user", "id": "user-a"},
            "subject": None,
        },
    )

    assert result["uploaded_by_snapshot_ref"]["status"] == "UNKNOWN"
