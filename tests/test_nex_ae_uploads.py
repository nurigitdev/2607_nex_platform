from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_ae_api.uploads as ae_uploads
from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_OA, SESSION_COOKIE_NAME
from nex_ae_api.uploads import (
    AE_MULTIPART_UPLOAD_ROUTE,
    HttpCxUploadClient,
    OWNERSHIP_COMPATIBILITY_MODE,
    OWNERSHIP_REF_SCHEMA_VERSION,
    UPLOAD_OWNER_RESOLVER_DISABLED,
    UPLOAD_OWNER_RESOLVER_ENSURE,
    UPLOAD_OWNER_RESOLVER_VERIFY,
    UploadHandoffError,
    UploadHandoffStore,
    build_cx_upload_payload,
    build_multipart_upload_source_payload,
    build_upload_ownership_ref,
    build_upload_handoff_record,
    non_negative_int,
    normalize_upload_owner_resolver_mode,
    optional_non_negative_int,
    owner_scope_from_payload,
    register_upload_routes,
    required_hash,
    resolve_upload_ownership,
    sha256_bytes,
    upload_handoff_status,
)
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    SubjectRegistryResolverError,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SOURCE_HASH = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610"
OWNER_REF = {
    "ownership_schema_version": OWNERSHIP_REF_SCHEMA_VERSION,
    "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
    "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
    "uploaded_by_subject_ref": {"type": "oa.user", "id": "user-a"},
    "legacy": {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
    "compatibility_mode": OWNERSHIP_COMPATIBILITY_MODE,
}


class FakeCxUploadClient:
    def __init__(self, *, dedupe_status: str = "CREATED") -> None:
        self.dedupe_status = dedupe_status
        self.calls: list[dict[str, Any]] = []

    def register_upload(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append({"payload": payload, "request_id": request_id, "trace_id": trace_id})
        size_bytes = payload.get("size_bytes")
        if not isinstance(size_bytes, int):
            size_bytes = len(payload.get("content_text", ""))
        source_sha256 = payload.get("source_sha256")
        if not isinstance(source_sha256, str):
            source_sha256 = SOURCE_HASH
        existing_document_id = "doc-001" if self.dedupe_status == "ALREADY_EXISTS" else None
        return {
            "document_id": "doc-001",
            "upload_id": "upload-001",
            "filename": payload["filename"],
            "content_type": payload["content_type"],
            "size_bytes": size_bytes,
            "source_sha256": source_sha256,
            "extraction": {
                "status": "PENDING",
                "job_id": "job-001",
                "markdown_available": False,
            },
            "dedupe": {
                "status": self.dedupe_status,
                "existing_document_id": existing_document_id,
            },
        }


class FailingCxUploadClient:
    def register_upload(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        raise UploadHandoffError(
            status_code=503,
            error_code="cx.upload_unavailable",
            detail="CX upload unavailable.",
            retryable=True,
        )


class FakeOwnerResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def resolve_ownership_ref(
        self,
        ownership_ref: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
        ensure: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "ownership_ref": ownership_ref,
                "request_id": request_id,
                "trace_id": trace_id,
                "ensure": ensure,
            }
        )
        return {
            "resolver_schema_version": "oa_subject_registry_resolver.v1",
            "resolution_status": "RESOLVED",
            "ensure": ensure,
        }


class FailingOwnerResolver:
    def resolve_ownership_ref(
        self,
        ownership_ref: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
        ensure: bool = False,
    ) -> dict[str, Any]:
        raise SubjectRegistryResolverError(
            status_code=404,
            error_code="oa.subject_not_found",
            detail="Subject was not found.",
            retryable=False,
        )


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def user_headers(
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id=tenant_id,
        user_id=user_id,
        scopes=[DEFAULT_USER_SCOPE, "documents:upload"],
        roles=["employee"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_client(
    cx_client: FakeCxUploadClient | FailingCxUploadClient | None = None,
    *,
    owner_resolver: FakeOwnerResolver | FailingOwnerResolver | None = None,
    owner_resolver_mode: str | None = None,
    oa_session_client: object | None = None,
    session_mode: str | None = None,
) -> tuple[TestClient, UploadHandoffStore, FakeCxUploadClient | FailingCxUploadClient]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = UploadHandoffStore()
    client = cx_client or FakeCxUploadClient()
    register_upload_routes(
        app,
        store=store,
        cx_client=client,
        owner_resolver=owner_resolver,
        owner_resolver_mode=owner_resolver_mode,
        oa_session_client=oa_session_client,
        session_mode=session_mode,
    )
    return TestClient(app), store, client


def test_build_cx_upload_payload_forwards_owner_scope_and_mock_text() -> None:
    payload = build_cx_upload_payload(
        {
            "filename": " report.md ",
            "content_type": "text/markdown",
            "content_text": "hello",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "source_sha256": SOURCE_HASH,
            "size_bytes": 5,
        },
        trace_id=TRACE_ID,
    )

    assert payload == {
        "trace_id": TRACE_ID,
        "filename": "report.md",
        "content_type": "text/markdown",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "ownership_ref": OWNER_REF,
        "content_text": "hello",
        "source_sha256": SOURCE_HASH,
        "size_bytes": 5,
    }


def test_build_cx_upload_payload_accepts_base64_source_boundary() -> None:
    payload = build_cx_upload_payload(
        {
            "filename": "source.bin",
            "content_type": "application/octet-stream",
            "content_base64": "AAFiaW5hcnk=",
            "source_sha256": SOURCE_HASH,
            "size_bytes": 8,
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        trace_id=TRACE_ID,
    )

    assert payload["content_base64"] == "AAFiaW5hcnk="
    assert payload["source_sha256"] == SOURCE_HASH
    assert payload["size_bytes"] == 8
    assert "content_text" not in payload


def test_build_cx_upload_payload_accepts_canonical_ownership_ref() -> None:
    ownership_ref = {
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
        "owner_subject_ref": {"type": "oa.user", "id": "user-b"},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": "uploader-b"},
    }

    payload = build_cx_upload_payload(
        {
            "filename": "report.md",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
            "ownership_ref": ownership_ref,
            "content_text": "hello",
        },
        trace_id=TRACE_ID,
    )

    assert payload["tenant_id"] == "tenant-b"
    assert payload["owner_user_id"] == "user-b"
    assert payload["ownership_ref"] == {
        "ownership_schema_version": OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
        "owner_subject_ref": {"type": "oa.user", "id": "user-b"},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": "uploader-b"},
        "legacy": {"tenant_id": "tenant-b", "owner_user_id": "user-b"},
        "compatibility_mode": OWNERSHIP_COMPATIBILITY_MODE,
    }


def test_upload_validation_rejects_invalid_inputs() -> None:
    assert owner_scope_from_payload({}) == ("local-tenant", "local-user")
    assert build_upload_ownership_ref({}) == {
        "ownership_schema_version": OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": {"type": "oa.tenant", "id": "local-tenant"},
        "owner_subject_ref": {"type": "oa.user", "id": "local-user"},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": "local-user"},
        "legacy": {"tenant_id": "local-tenant", "owner_user_id": "local-user"},
        "compatibility_mode": OWNERSHIP_COMPATIBILITY_MODE,
    }
    assert owner_scope_from_payload(
        {
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
                "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
            }
        }
    ) == ("tenant-a", "user-a")
    assert required_hash(SOURCE_HASH) == SOURCE_HASH
    assert non_negative_int(0) == 0
    assert optional_non_negative_int(3, field_name="size_bytes") == 3
    assert optional_non_negative_int("0", field_name="size_bytes") == 0
    assert optional_non_negative_int("", field_name="size_bytes") is None

    invalid_payloads = [
        {},
        {"filename": ""},
        {"filename": "x", "tenant_id": ""},
        {"filename": "x", "content_text": []},
        {"filename": "x", "content_text": "hello", "content_base64": "aGVsbG8="},
        {"filename": "x", "content_base64": ""},
        {"filename": "x", "source_sha256": "BAD"},
        {"filename": "x", "size_bytes": -1},
        {"filename": "x", "ownership_ref": "owner-a"},
        {"filename": "x", "tenant_ref": "tenant-a"},
        {
            "filename": "x",
            "tenant_id": "tenant-a",
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
                "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
            },
        },
        {
            "filename": "x",
            "tenant_ref": {"type": "cx.tenant", "id": "tenant-a"},
        },
        {
            "filename": "x",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
                "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
            },
        },
        {
            "filename": "x",
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant"},
                "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
            },
        },
        {
            "filename": "x",
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
                "owner_subject_ref": {"type": "oa.group", "id": "user-a"},
            },
        },
    ]
    for payload in invalid_payloads:
        with pytest.raises(UploadHandoffError):
            build_cx_upload_payload(payload, trace_id=TRACE_ID)

    with pytest.raises(UploadHandoffError):
        non_negative_int("1")
    with pytest.raises(UploadHandoffError):
        optional_non_negative_int("not-int", field_name="size_bytes")
    with pytest.raises(UploadHandoffError):
        required_hash("")


def test_build_multipart_upload_source_payload_computes_hash_and_base64() -> None:
    file_bytes = b"\x00source file bytes"
    payload = build_multipart_upload_source_payload(
        file_bytes=file_bytes,
        file_filename="source.bin",
        file_content_type="application/octet-stream",
        workspace_id="workspace-001",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_sha256=sha256_bytes(file_bytes),
        size_bytes=str(len(file_bytes)),
    )

    assert payload == {
        "filename": "source.bin",
        "content_type": "application/octet-stream",
        "size_bytes": len(file_bytes),
        "source_sha256": sha256_bytes(file_bytes),
        "content_base64": "AHNvdXJjZSBmaWxlIGJ5dGVz",
        "workspace_id": "workspace-001",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
    }

    without_optional_hash = build_multipart_upload_source_payload(
        file_bytes=file_bytes,
        file_filename="source.bin",
        file_content_type=None,
    )
    assert without_optional_hash["source_sha256"] == sha256_bytes(file_bytes)
    assert without_optional_hash["content_type"] == "application/octet-stream"


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        ({"file_bytes": b""}, "ae.upload_file_empty"),
        ({"source_sha256": SOURCE_HASH}, "ae.upload_hash_mismatch"),
        ({"size_bytes": "999"}, "ae.upload_size_mismatch"),
        ({"size_bytes": "bad"}, "ae.upload_size_invalid"),
    ],
)
def test_build_multipart_upload_source_payload_rejects_bad_file_contract(
    kwargs: dict[str, object],
    error_code: str,
) -> None:
    base_kwargs = {
        "file_bytes": b"file bytes",
        "file_filename": "source.bin",
        "file_content_type": "application/octet-stream",
    }
    base_kwargs.update(kwargs)

    with pytest.raises(UploadHandoffError) as exc:
        build_multipart_upload_source_payload(**base_kwargs)

    assert exc.value.error_code == error_code


def test_build_upload_handoff_record_redacts_source_and_storage_details() -> None:
    cx_payload = build_cx_upload_payload(
        {"filename": "report.md", "content_text": "hello"},
        trace_id=TRACE_ID,
    )
    cx_record = FakeCxUploadClient().register_upload(
        cx_payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    handoff = build_upload_handoff_record(
        source_payload={"workspace_id": "workspace-001"},
        cx_payload=cx_payload,
        cx_record=cx_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert handoff["status"] == "QUEUED"
    assert handoff["ownership_ref"]["tenant_ref"] == {
        "type": "oa.tenant",
        "id": "local-tenant",
    }
    assert handoff["ownership_ref"]["owner_subject_ref"] == {
        "type": "oa.user",
        "id": "local-user",
    }
    assert handoff["source"]["source_text_hash"]
    assert handoff["cx_document_ref"]["ingestion_job_id"] == "job-001"
    assert handoff["metadata"] == {
        "raw_source_stored_in_ae": False,
        "cx_storage_redacted": True,
    }
    assert "hello" not in str(handoff)
    assert "source_storage_path" not in str(handoff)


def test_build_upload_handoff_record_redacts_base64_source_content() -> None:
    cx_payload = build_cx_upload_payload(
        {
            "filename": "source.bin",
            "content_type": "application/octet-stream",
            "content_base64": "c2VjcmV0LWJ5dGVz",
            "source_sha256": SOURCE_HASH,
            "size_bytes": 12,
        },
        trace_id=TRACE_ID,
    )
    cx_record = FakeCxUploadClient().register_upload(
        cx_payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    handoff = build_upload_handoff_record(
        source_payload={"workspace_id": "workspace-001"},
        cx_payload=cx_payload,
        cx_record=cx_record,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert handoff["source"]["source_text_hash"] is None
    assert handoff["source"]["source_sha256"] == SOURCE_HASH
    assert handoff["metadata"]["raw_source_stored_in_ae"] is False
    assert "c2VjcmV0LWJ5dGVz" not in str(handoff)
    assert "secret-bytes" not in str(handoff)


def test_upload_owner_resolver_mode_normalization_and_disabled_skip() -> None:
    assert normalize_upload_owner_resolver_mode(None) == UPLOAD_OWNER_RESOLVER_DISABLED
    assert normalize_upload_owner_resolver_mode(" VERIFY ") == UPLOAD_OWNER_RESOLVER_VERIFY
    assert normalize_upload_owner_resolver_mode("ensure") == UPLOAD_OWNER_RESOLVER_ENSURE
    assert (
        resolve_upload_ownership(
            OWNER_REF,
            owner_resolver=None,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_DISABLED,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
        is None
    )

    with pytest.raises(UploadHandoffError) as bad_mode:
        normalize_upload_owner_resolver_mode("raw-identity")

    assert bad_mode.value.error_code == "ae.upload_owner_resolver_mode_invalid"


def test_resolve_upload_ownership_verify_and_ensure_modes() -> None:
    resolver = FakeOwnerResolver()

    verified = resolve_upload_ownership(
        OWNER_REF,
        owner_resolver=resolver,
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    ensured = resolve_upload_ownership(
        OWNER_REF,
        owner_resolver=resolver,
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_ENSURE,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert verified["resolution_status"] == "RESOLVED"
    assert ensured["ensure"] is True
    assert [call["ensure"] for call in resolver.calls] == [False, True]
    assert resolver.calls[0]["ownership_ref"] == OWNER_REF


def test_resolve_upload_ownership_requires_configured_resolver_and_maps_errors() -> None:
    with pytest.raises(UploadHandoffError) as missing_resolver:
        resolve_upload_ownership(
            OWNER_REF,
            owner_resolver=None,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert missing_resolver.value.status_code == 503
    assert missing_resolver.value.error_code == "ae.upload_owner_resolver_unavailable"
    assert missing_resolver.value.retryable is True

    with pytest.raises(UploadHandoffError) as unresolved:
        resolve_upload_ownership(
            OWNER_REF,
            owner_resolver=FailingOwnerResolver(),
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert unresolved.value.status_code == 404
    assert unresolved.value.error_code == "ae.upload_owner_unresolved"
    assert unresolved.value.detail == "Subject was not found."


def test_upload_handoff_status_maps_duplicate() -> None:
    assert upload_handoff_status({"dedupe": {"status": "CREATED"}}) == "QUEUED"
    assert (
        upload_handoff_status({"dedupe": {"status": "ALREADY_EXISTS"}})
        == "ALREADY_EXISTS"
    )


def test_upload_routes_accept_readback_duplicate_and_auth() -> None:
    client, store, cx_client = build_client()
    unauthorized = client.post("/api/v1/uploads", json={"filename": "report.md"})
    created = client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": "workspace-001",
            "filename": "report.md",
            "content_type": "text/markdown",
            "content_text": "hello",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        headers=auth_headers(),
    )
    duplicate_client, _, _ = build_client(FakeCxUploadClient(dedupe_status="ALREADY_EXISTS"))
    duplicate = duplicate_client.post(
        "/api/v1/uploads",
        json={"filename": "report.md", "content_text": "hello"},
        headers=auth_headers(),
    )

    payload = created.json()
    readback = client.get(
        f"/api/v1/uploads/{payload['upload_handoff_id']}",
        headers=auth_headers(),
    )
    unauthorized_readback = client.get(f"/api/v1/uploads/{payload['upload_handoff_id']}")

    assert unauthorized.status_code == 401
    assert unauthorized_readback.status_code == 401
    assert created.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "ALREADY_EXISTS"
    assert store.get(payload["upload_handoff_id"]) == payload
    assert readback.status_code == 200
    assert readback.json()["upload_handoff_id"] == payload["upload_handoff_id"]
    assert isinstance(cx_client, FakeCxUploadClient)
    assert cx_client.calls[0]["payload"]["owner_user_id"] == "user-a"
    assert cx_client.calls[0]["payload"]["ownership_ref"] == OWNER_REF


def test_upload_routes_accept_browser_user_and_scope_payload_to_claims() -> None:
    client, store, cx_client = build_client()

    created = client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": "workspace-001",
            "filename": "report.md",
            "content_type": "text/markdown",
            "content_text": "hello",
        },
        headers=user_headers(),
    )

    payload = created.json()
    same_user_read = client.get(
        f"/api/v1/uploads/{payload['upload_handoff_id']}",
        headers=user_headers(),
    )
    other_user_read = client.get(
        f"/api/v1/uploads/{payload['upload_handoff_id']}",
        headers=user_headers(user_id="user-b"),
    )

    assert created.status_code == 202
    assert payload["tenant_id"] == "tenant-a"
    assert payload["owner_user_id"] == "user-a"
    assert payload["ownership_ref"] == OWNER_REF
    assert store.get(payload["upload_handoff_id"]) == payload
    assert same_user_read.status_code == 200
    assert other_user_read.status_code == 403
    assert other_user_read.json()["error_code"] == "ae.browser_owner_scope_mismatch"
    assert isinstance(cx_client, FakeCxUploadClient)
    assert cx_client.calls[0]["payload"]["tenant_id"] == "tenant-a"
    assert cx_client.calls[0]["payload"]["owner_user_id"] == "user-a"


def test_multipart_upload_route_forwards_file_bytes_to_cx_without_storing_in_ae() -> None:
    client, store, cx_client = build_client()
    file_bytes = b"\x00browser multipart bytes"

    response = client.post(
        AE_MULTIPART_UPLOAD_ROUTE,
        data={
            "workspace_id": "workspace-file",
            "size_bytes": str(len(file_bytes)),
            "source_sha256": sha256_bytes(file_bytes),
        },
        files={"file": ("source.bin", file_bytes, "application/octet-stream")},
        headers=user_headers(),
    )

    payload = response.json()
    cx_payload = cx_client.calls[0]["payload"]
    assert response.status_code == 202
    assert payload["workspace_id"] == "workspace-file"
    assert payload["tenant_id"] == "tenant-a"
    assert payload["owner_user_id"] == "user-a"
    assert payload["source"]["size_bytes"] == len(file_bytes)
    assert payload["source"]["source_sha256"] == sha256_bytes(file_bytes)
    assert payload["metadata"] == {
        "raw_source_stored_in_ae": False,
        "cx_storage_redacted": True,
    }
    assert store.get(payload["upload_handoff_id"]) == payload
    assert cx_payload["tenant_id"] == "tenant-a"
    assert cx_payload["owner_user_id"] == "user-a"
    assert cx_payload["content_base64"] == "AGJyb3dzZXIgbXVsdGlwYXJ0IGJ5dGVz"
    assert cx_payload["source_sha256"] == sha256_bytes(file_bytes)
    assert "content_base64" not in str(payload)
    assert "browser multipart bytes" not in str(payload)


def test_multipart_upload_route_rejects_unauthorized_and_owner_mismatch_before_cx_call() -> None:
    unauthorized_client, _, unauthorized_cx = build_client()
    mismatch_client, _, mismatch_cx = build_client()

    unauthorized = unauthorized_client.post(
        AE_MULTIPART_UPLOAD_ROUTE,
        files={"file": ("source.bin", b"file bytes", "application/octet-stream")},
    )
    mismatch = mismatch_client.post(
        AE_MULTIPART_UPLOAD_ROUTE,
        data={"owner_user_id": "user-b"},
        files={"file": ("source.bin", b"file bytes", "application/octet-stream")},
        headers=user_headers(user_id="user-a"),
    )

    assert unauthorized.status_code == 401
    assert mismatch.status_code == 403
    assert mismatch.json()["error_code"] == "ae.browser_owner_scope_mismatch"
    assert unauthorized_cx.calls == []
    assert mismatch_cx.calls == []


def test_multipart_upload_route_rejects_hash_mismatch_before_cx_call() -> None:
    client, _, cx_client = build_client()

    response = client.post(
        AE_MULTIPART_UPLOAD_ROUTE,
        data={"source_sha256": SOURCE_HASH},
        files={"file": ("source.bin", b"actual bytes", "application/octet-stream")},
        headers=user_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ae.upload_hash_mismatch"
    assert cx_client.calls == []


def test_upload_routes_accept_oa_mode_browser_cookie_and_scope_payload_to_claims() -> None:
    class FakeOaSessionClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def introspect_session(self, session_id: str, **kwargs: object) -> dict[str, Any]:
            self.calls.append({"session_id": session_id, **kwargs})
            return {
                "active": session_id == "oa-upload-session",
                "inactive_reason": None if session_id == "oa-upload-session" else "missing",
                "session": {
                    "browser_session_schema_version": "oa_browser_session.v1",
                    "session_id": session_id,
                    "status": "ACTIVE",
                    "issuer": "nex-oa",
                    "audience": "nex-ae-api",
                    "token_use": "user",
                    "tenant_ref": {"type": "oa.tenant", "id": "tenant-oa"},
                    "subject_ref": {"type": "oa.user", "id": "user-oa"},
                    "scopes": [DEFAULT_USER_SCOPE, "documents:upload"],
                    "roles": ["employee"],
                    "issued_at": "2026-08-13T00:00:00Z",
                    "expires_at": "2026-08-13T01:00:00Z",
                    "auth_time": "2026-08-13T00:00:00Z",
                },
            }

    oa_session_client = FakeOaSessionClient()
    client, _, cx_client = build_client(
        oa_session_client=oa_session_client,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    client.cookies.set(SESSION_COOKIE_NAME, "oa-upload-session")

    response = client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": "workspace-oa",
            "filename": "metadata-only.md",
            "content_type": "text/markdown",
            "source_sha256": SOURCE_HASH,
            "size_bytes": 1536,
        },
    )

    assert response.status_code == 202
    assert len(oa_session_client.calls) == 1
    assert isinstance(cx_client, FakeCxUploadClient)
    assert cx_client.calls[0]["payload"]["tenant_id"] == "tenant-oa"
    assert cx_client.calls[0]["payload"]["owner_user_id"] == "user-oa"
    assert "content_text" not in cx_client.calls[0]["payload"]
    assert cx_client.calls[0]["payload"]["source_sha256"] == SOURCE_HASH


def test_upload_route_rejects_browser_owner_scope_mismatch_before_cx_call() -> None:
    client, _, cx_client = build_client()

    response = client.post(
        "/api/v1/uploads",
        json={
            "filename": "report.md",
            "content_text": "hello",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-b",
        },
        headers=user_headers(),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ae.browser_owner_scope_mismatch"
    assert isinstance(cx_client, FakeCxUploadClient)
    assert cx_client.calls == []


def test_upload_route_resolves_owner_before_forwarding_to_cx() -> None:
    owner_resolver = FakeOwnerResolver()
    client, _, cx_client = build_client(
        owner_resolver=owner_resolver,
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
    )

    response = client.post(
        "/api/v1/uploads",
        json={
            "filename": "report.md",
            "content_text": "hello",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 202
    assert len(owner_resolver.calls) == 1
    assert owner_resolver.calls[0]["ensure"] is False
    assert owner_resolver.calls[0]["request_id"] == REQUEST_ID
    assert isinstance(cx_client, FakeCxUploadClient)
    assert len(cx_client.calls) == 1
    assert cx_client.calls[0]["payload"]["ownership_ref"] == OWNER_REF


def test_upload_route_builds_default_resolver_when_env_mode_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_resolver = FakeOwnerResolver()
    monkeypatch.setenv("NEX_AE_UPLOAD_OWNER_RESOLVER_MODE", UPLOAD_OWNER_RESOLVER_VERIFY)
    monkeypatch.setattr(
        ae_uploads,
        "build_default_subject_registry_resolver",
        lambda *, caller_service_id: owner_resolver,
    )

    client, _, cx_client = build_client()
    response = client.post(
        "/api/v1/uploads",
        json={
            "filename": "report.md",
            "content_text": "hello",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 202
    assert len(owner_resolver.calls) == 1
    assert owner_resolver.calls[0]["ensure"] is False
    assert isinstance(cx_client, FakeCxUploadClient)
    assert len(cx_client.calls) == 1


def test_upload_route_can_ensure_owner_before_forwarding_to_cx() -> None:
    owner_resolver = FakeOwnerResolver()
    client, _, _ = build_client(
        owner_resolver=owner_resolver,
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_ENSURE,
    )

    response = client.post(
        "/api/v1/uploads",
        json={"filename": "report.md", "content_text": "hello"},
        headers=auth_headers(),
    )

    assert response.status_code == 202
    assert owner_resolver.calls[0]["ensure"] is True


def test_upload_route_reports_owner_resolution_failure_before_cx_call() -> None:
    cx_client = FakeCxUploadClient()
    client, _, _ = build_client(
        cx_client,
        owner_resolver=FailingOwnerResolver(),
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
    )

    response = client.post(
        "/api/v1/uploads",
        json={"filename": "report.md", "content_text": "hello"},
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.upload_owner_unresolved"
    assert cx_client.calls == []


def test_upload_routes_report_invalid_missing_and_cx_failure() -> None:
    client, _, _ = build_client()
    invalid = client.post("/api/v1/uploads", json={"filename": ""}, headers=auth_headers())
    missing = client.get("/api/v1/uploads/missing", headers=auth_headers())
    failing_client, _, _ = build_client(FailingCxUploadClient())
    failed = failing_client.post(
        "/api/v1/uploads",
        json={"filename": "report.md"},
        headers=auth_headers(),
    )

    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "ae.upload_filename_required"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.upload_handoff_not_found"
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "cx.upload_unavailable"
    assert failed.json()["retryable"] is True


def test_http_cx_upload_client_sends_service_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    payloads: list[dict[str, Any]] = []

    def fake_post(
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        payloads.append(json)
        return httpx.Response(
            status_code=202,
            json={
                "document_id": "doc-001",
                "upload_id": "upload-001",
                "filename": "report.md",
                "content_type": "text/markdown",
                "size_bytes": 5,
                "source_sha256": SOURCE_HASH,
                "extraction": {
                    "status": "PENDING",
                    "job_id": "job-001",
                    "markdown_available": False,
                },
                "dedupe": {
                    "status": "CREATED",
                    "existing_document_id": None,
                },
            },
        )

    monkeypatch.setattr(ae_uploads.httpx, "post", fake_post)
    response = HttpCxUploadClient(base_url="http://cx", timeout_seconds=2.5).register_upload(
        {"filename": "report.md"},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    prepared_payload = build_cx_upload_payload(
        {"filename": "second.md", "content_text": "hello"},
        trace_id=TRACE_ID,
    )
    second_response = HttpCxUploadClient(
        base_url="http://cx",
        timeout_seconds=2.5,
    ).register_upload(
        prepared_payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert captured["url"] == "http://cx/api/v1/documents/uploads"
    assert captured["timeout"] == 2.5
    assert captured["headers"]["X-Service-ID"] == "nex-ae-api"
    assert payloads[0]["ownership_ref"]["tenant_ref"] == {
        "type": "oa.tenant",
        "id": "local-tenant",
    }
    assert payloads[1] == prepared_payload
    assert response["document_id"] == "doc-001"
    assert second_response["document_id"] == "doc-001"


def test_http_cx_upload_client_maps_error_body_and_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post_error(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            status_code=409,
            json={
                "error_code": "cx.conflict",
                "detail": "Conflict.",
                "retryable": False,
            },
        )

    monkeypatch.setattr(ae_uploads.httpx, "post", post_error)
    with pytest.raises(UploadHandoffError) as exc:
        HttpCxUploadClient(base_url="http://cx").register_upload(
            {"filename": "report.md"},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc.value.error_code == "cx.conflict"

    def post_bad_json(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=503, content=b"unavailable")

    monkeypatch.setattr(ae_uploads.httpx, "post", post_bad_json)
    with pytest.raises(UploadHandoffError) as bad_json:
        HttpCxUploadClient(base_url="http://cx").register_upload(
            {"filename": "report.md"},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert bad_json.value.error_code == "cx.upload_request_failed"

    def post_json_list(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=502, json=["unavailable"])

    monkeypatch.setattr(ae_uploads.httpx, "post", post_json_list)
    with pytest.raises(UploadHandoffError) as json_list:
        HttpCxUploadClient(base_url="http://cx").register_upload(
            {"filename": "report.md"},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert json_list.value.error_code == "cx.upload_request_failed"
