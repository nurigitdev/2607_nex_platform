from __future__ import annotations

from time import time

from fastapi.testclient import TestClient
import pytest

from nex_oa.auth_events import InMemoryOaAuthEventRepository
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.signed_token_api import (
    OA_INTROSPECTION_SCOPE,
    OA_REVOCATION_SCOPE,
    _bearer_token,
    _payload,
    register_signed_token_routes,
)
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService
from nex_oa.token_signing import (
    InMemoryOaRsaSigningProvider,
    UnavailableOaRsaSigningProvider,
)
from nex_oa.token_validation_service import OaSignedTokenValidationService
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
)


def _runtime(*, emitter: OperationalEventEmitter | None = None) -> dict[str, object]:
    now = int(time())
    principals = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    principals.upsert_principal(
        {
            "principal_id": "cx-runtime",
            "service_id": "nex-cx",
            "display_name": "CX Runtime",
            "allowed_audiences": ["nex-oa", "nex-cx"],
            "allowed_scopes": [
                OA_INTROSPECTION_SCOPE,
                OA_REVOCATION_SCOPE,
                "document:read",
            ],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "cx-runtime",
        lifetime_days=1,
        now_epoch=now - 10,
        credential_id="cred-cx-runtime",
        client_secret="api-secret",
    )
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-api"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(), deployment_profile="test"
    )
    keys.register_key(
        {
            "key_id": "oa-key-api",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(reference, key_id="oa-key-api"),
            "private_key_ref": reference,
            "published_at": now - 330,
            "activate_at": now,
            "sign_until": now + 600,
            "verify_until": now + 930,
        }
    )
    keys.set_key_state(
        "oa-key-api", target_state="ACTIVE", expected_revision=1, now_epoch=now
    )
    exchange = OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=keys,
        signing_provider=signer,
    )
    validation = OaSignedTokenValidationService(
        signing_key_service=keys,
        principal_service=principals,
    )
    store = InMemoryOperationalEventStore()
    auth_events = InMemoryOaAuthEventRepository()
    app = build_service_app(
        SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False
    )
    register_signed_token_routes(
        app,
        token_exchange_service=exchange,
        validation_service=validation,
        signing_key_service=keys,
        audit_emitter=emitter
        or OperationalEventEmitter(service_id="nex-oa", store=store),
        auth_event_repository=auth_events,
    )
    caller = exchange.exchange(
        {
            "grant_type": "client_credentials",
            "credential_id": "cred-cx-runtime",
            "client_secret": "api-secret",
            "audience": "nex-oa",
            "scope": f"{OA_INTROSPECTION_SCOPE} {OA_REVOCATION_SCOPE}",
        }
    )["access_token"]
    return {
        "client": TestClient(app),
        "app": app,
        "principals": principals,
        "keys": keys,
        "exchange": exchange,
        "validation": validation,
        "store": store,
        "auth_events": auth_events,
        "caller": caller,
    }


def _token_request(**changes: object) -> dict[str, object]:
    return {
        "grant_type": "client_credentials",
        "credential_id": "cred-cx-runtime",
        "client_secret": "api-secret",
        "audience": "nex-cx",
        "scope": "document:read",
        **changes,
    }


def _auth(runtime: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {runtime['caller']}"}


def test_jwks_token_introspection_and_revocation_routes() -> None:
    runtime = _runtime()
    client = runtime["client"]
    jwks = client.get("/.well-known/jwks.json")  # type: ignore[union-attr]
    issued = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/service-token",
        json=_token_request(),
        headers={"X-Request-ID": "request-1269"},
    )

    assert jwks.status_code == 200
    assert jwks.json()["key_count"] == 1
    assert "d" not in jwks.json()["keys"][0]
    assert issued.status_code == 200
    token = issued.json()["access_token"]
    assert token.count(".") == 2
    assert issued.json()["audit_event"]["ok"] is True

    active = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/introspect",
        json={"token": token, "audience": "nex-cx", "required_scopes": ["document:read"]},
        headers=_auth(runtime),
    )
    revoked = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/revoke",
        json={"token": token, "audience": "nex-cx", "reason_code": "OPERATOR"},
        headers=_auth(runtime),
    )
    inactive = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/introspect",
        json={"token": token, "audience": "nex-cx"},
        headers=_auth(runtime),
    )

    assert active.json()["active"] is True
    assert len(active.json()["token_id_digest"]) == 64
    assert revoked.status_code == 200
    assert "jti" not in revoked.json()
    assert inactive.json()["active"] is False
    assert inactive.json()["reason_code"] == "oa.token_revoked"
    serialized = str(runtime["store"].events)  # type: ignore[union-attr]
    assert "api-secret" not in serialized
    assert token not in serialized


def test_introspection_and_revocation_require_signed_scoped_bearer() -> None:
    runtime = _runtime()
    client = runtime["client"]
    body = {"token": "target", "audience": "nex-cx"}
    assert client.post("/api/v1/auth/introspect", json=body).status_code == 401  # type: ignore[union-attr]
    assert client.post("/api/v1/auth/revoke", json=body).status_code == 401  # type: ignore[union-attr]

    limited = runtime["exchange"].exchange(  # type: ignore[union-attr]
        _token_request(audience="nex-oa", scope="document:read")
    )["access_token"]
    response = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/introspect",
        json=body,
        headers={"Authorization": f"Bearer {limited}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "oa.token_scope_forbidden"
    events = runtime["auth_events"].events  # type: ignore[union-attr]
    assert [event["event_type"] for event in events] == [
        "SERVICE_AUTH_FAILED",
        "SERVICE_AUTH_FAILED",
        "SERVICE_AUTH_FAILED",
    ]
    assert all(event["outcome"] == "BLOCKED" for event in events)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/auth/service-token", {**_token_request(), "secret_hash": "x"}),
        ("/api/v1/auth/service-token", {"grant_type": "client_credentials"}),
        ("/api/v1/auth/introspect", {"token": "x", "audience": "nex-cx", "required_scopes": "bad"}),
        ("/api/v1/auth/revoke", {"token": "x", "audience": "nex-cx"}),
    ],
)
def test_routes_reject_unknown_incomplete_or_invalid_payloads(
    path: str, body: dict[str, object]
) -> None:
    runtime = _runtime()
    headers = {} if path.endswith("service-token") else _auth(runtime)
    response = runtime["client"].post(path, json=body, headers=headers)  # type: ignore[union-attr]
    assert response.status_code == 400
    assert response.json()["error_code"] == "oa.token_request_invalid"


def test_exchange_errors_and_unavailable_custody_are_problem_details() -> None:
    runtime = _runtime()
    rejected = runtime["client"].post(  # type: ignore[union-attr]
        "/api/v1/auth/service-token",
        json=_token_request(client_secret="wrong"),
    )
    assert rejected.status_code == 401
    assert rejected.json()["error_code"] == "oa.service_credential_rejected"
    event = runtime["auth_events"].events[-1]  # type: ignore[union-attr]
    assert event["event_type"] == "SERVICE_AUTH_FAILED"
    assert event["credential_id"] == "cred-cx-runtime"
    assert event["details"] == {
        "operation": "service_token_exchange",
        "error_code": "oa.service_credential_rejected",
    }

    runtime["exchange"].signing_provider = UnavailableOaRsaSigningProvider()  # type: ignore[union-attr]
    unavailable = runtime["client"].post(  # type: ignore[union-attr]
        "/api/v1/auth/service-token", json=_token_request()
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "oa.signing_key_custody_unavailable"
    assert len(runtime["auth_events"].events) == 1  # type: ignore[union-attr]


def test_inactive_and_invalid_target_tokens_emit_safe_validation_events() -> None:
    runtime = _runtime()
    client = runtime["client"]
    token = runtime["exchange"].exchange(_token_request())["access_token"]  # type: ignore[union-attr]
    runtime["keys"].revoke_token_claims(  # type: ignore[union-attr]
        runtime["validation"].validate(token, expected_audience="nex-cx"),  # type: ignore[union-attr]
        reason_code="OPERATOR",
    )

    inactive = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/introspect",
        json={"token": token, "audience": "nex-cx"},
        headers=_auth(runtime),
    )
    invalid = client.post(  # type: ignore[union-attr]
        "/api/v1/auth/revoke",
        json={
            "token": "malformed.token.value",
            "audience": "nex-cx",
            "reason_code": "OPERATOR",
        },
        headers=_auth(runtime),
    )

    assert inactive.status_code == 200
    assert inactive.json()["active"] is False
    assert invalid.status_code == 401
    events = runtime["auth_events"].events  # type: ignore[union-attr]
    assert [event["event_type"] for event in events] == [
        "TOKEN_VALIDATION_FAILED",
        "TOKEN_VALIDATION_FAILED",
    ]
    assert events[0]["details"] == {
        "operation": "token_introspection",
        "error_code": "oa.token_revoked",
    }
    assert events[1]["details"] == {
        "operation": "token_revocation",
        "error_code": "oa.token_encoding_invalid",
    }
    serialized = str(events)
    assert token not in serialized
    assert "malformed.token.value" not in serialized


def test_bad_bearer_and_audit_failure_paths() -> None:
    for value in (None, "Basic value", "Bearer ", "Bearer  padded "):
        with pytest.raises(OaSignedTokenError):
            _bearer_token(value)
    assert _bearer_token("Bearer compact.jwt.value") == "compact.jwt.value"

    class FailingStore:
        def append(self, event: object) -> None:
            raise RuntimeError("private audit failure")

    runtime = _runtime(
        emitter=OperationalEventEmitter(service_id="nex-oa", store=FailingStore())
    )
    response = runtime["client"].post(  # type: ignore[union-attr]
        "/api/v1/auth/service-token", json=_token_request()
    )
    assert response.status_code == 200
    assert response.json()["audit_event"]["ok"] is False


def test_payload_helper_and_main_route_replacement() -> None:
    with pytest.raises(OaSignedTokenError, match="unsupported"):
        _payload({"private_key": "x"}, allowed=frozenset(), required=())
    with pytest.raises(OaSignedTokenError, match="required"):
        _payload({}, allowed=frozenset({"token"}), required=("token",))
    assert _payload({"token": "x"}, allowed=frozenset({"token"}), required=("token",)) == {"token": "x"}

    from nex_oa.main import app

    paths = [route.path for route in app.routes]
    assert paths.count("/api/v1/auth/service-token") == 1
    assert paths.count("/api/v1/auth/introspect") == 1
    assert "/api/v1/auth/revoke" in paths
    assert "/.well-known/jwks.json" in paths
