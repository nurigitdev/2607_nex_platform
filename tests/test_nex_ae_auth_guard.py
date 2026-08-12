from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from nex_ae_api.auth_guard import (
    AE_BROWSER_USER_AUTH_CONTEXT_SCHEMA_VERSION,
    BrowserAuthError,
    apply_claim_owner_scope,
    authorize_browser_user_request,
    build_browser_auth_summary,
    build_browser_user_auth_context,
    owner_scope_from_browser_context,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    ServiceClaims,
    UserClaims,
    issue_mock_service_token,
    issue_mock_user_token,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def user_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        scopes=scopes or [DEFAULT_USER_SCOPE, "documents:upload"],
        roles=["employee"],
        issued_at=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {issued.access_token}"}


def test_authorize_browser_user_request_accepts_user_token() -> None:
    app = FastAPI()

    @app.get("/guard")
    def guarded(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_browser_user_request(request, authorization)
        if not hasattr(result, "to_wire"):
            return result
        return build_browser_auth_summary(result)

    response = TestClient(app).get("/guard", headers=user_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_context_schema_version"] == (
        AE_BROWSER_USER_AUTH_CONTEXT_SCHEMA_VERSION
    )
    assert payload["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert payload["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert payload["token_use"] == "user"
    assert payload["owner_scope_authority"] == "claim"
    assert payload["metadata"]["service_token_accepted"] is False
    assert "access_token" not in payload


def test_authorize_browser_user_request_rejects_service_token_and_missing_scope() -> None:
    app = FastAPI()

    @app.get("/guard")
    def guarded(request: Request, authorization: str | None = Header(default=None)):
        return authorize_browser_user_request(
            request,
            authorization,
            required_scopes=["documents:upload"],
        )

    service_token = issue_mock_service_token(
        service_id="nex-oa",
        audience="nex-ae-api",
        scopes=[DEFAULT_SERVICE_SCOPE],
        issued_at=NOW,
    )

    service_response = TestClient(app).get(
        "/guard",
        headers={"Authorization": f"Bearer {service_token.access_token}"},
    )
    missing_scope_response = TestClient(app).get(
        "/guard",
        headers=user_headers(scopes=[DEFAULT_USER_SCOPE]),
    )

    assert service_response.status_code == 401
    assert service_response.json()["error_code"] == "TOKEN_FORMAT_INVALID"
    assert missing_scope_response.status_code == 401
    assert missing_scope_response.json()["error_code"] == "TOKEN_SCOPE_MISSING"


def test_build_browser_user_auth_context_rejects_wrong_claim_shape() -> None:
    service_claims = ServiceClaims(
        issuer="nex-oa",
        subject="service:nex-ae-api",
        audience="nex-ae-api",
        service_id="nex-ae-api",
        scopes=(DEFAULT_SERVICE_SCOPE,),
        issued_at="2026-08-12T12:00:00Z",
        expires_at="2026-08-12T13:00:00Z",
    )
    wrong_audience = UserClaims(
        issuer="nex-oa",
        subject="user:tenant-a:user-a",
        audience="nex-cx",
        tenant_id="tenant-a",
        user_id="user-a",
        scopes=(DEFAULT_USER_SCOPE,),
        roles=(),
        issued_at="2026-08-12T12:00:00Z",
        expires_at="2026-08-12T13:00:00Z",
    )

    with pytest.raises(BrowserAuthError, match="token_use=user"):
        build_browser_user_auth_context(  # type: ignore[arg-type]
            service_claims,
        )
    with pytest.raises(BrowserAuthError, match="audience=nex-ae-api"):
        build_browser_user_auth_context(wrong_audience)


def test_owner_scope_from_browser_context_is_claim_authoritative() -> None:
    context = build_browser_user_auth_context(
        issue_mock_user_token(
            tenant_id="tenant-a",
            user_id="user-a",
            issued_at=NOW,
        ).claims
    )

    owner_scope = owner_scope_from_browser_context(context)
    normalized = apply_claim_owner_scope(
        {
            "filename": "report.md",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        context,
    )

    assert owner_scope["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert owner_scope["owner_subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert normalized["tenant_id"] == "tenant-a"
    assert normalized["owner_user_id"] == "user-a"
    assert normalized["user_id"] == "user-a"
    assert normalized["ownership_ref"] == owner_scope
    assert normalized["actor_claims_ref"] == {
        "actor_type": "user",
        "actor_id": "user-a",
        "tenant_id": "tenant-a",
    }


def test_apply_claim_owner_scope_rejects_browser_payload_mismatches() -> None:
    context = build_browser_user_auth_context(
        issue_mock_user_token(
            tenant_id="tenant-a",
            user_id="user-a",
            issued_at=NOW,
        ).claims
    )

    for payload in [
        {"tenant_id": "tenant-b"},
        {"owner_user_id": "user-b"},
        {"user_id": "user-b"},
        {"ownership_ref": {"tenant_ref": {"id": "tenant-b"}}},
        {"ownership_ref": {"owner_subject_ref": {"id": "user-b"}}},
    ]:
        with pytest.raises(BrowserAuthError) as exc:
            apply_claim_owner_scope(payload, context)
        assert exc.value.status_code == 403
        assert exc.value.error_code == "ae.browser_owner_scope_mismatch"


def test_apply_claim_owner_scope_can_override_when_guard_is_disabled() -> None:
    context = build_browser_user_auth_context(
        issue_mock_user_token(
            tenant_id="tenant-a",
            user_id="user-a",
            issued_at=NOW,
        ).claims
    )

    normalized = apply_claim_owner_scope(
        {"tenant_id": "tenant-b", "owner_user_id": "user-b"},
        context,
        reject_mismatch=False,
    )

    assert normalized["tenant_id"] == "tenant-a"
    assert normalized["owner_user_id"] == "user-a"
