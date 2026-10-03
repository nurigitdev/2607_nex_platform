from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence

import httpx
import pytest
from fastapi.testclient import TestClient

from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime.app import SERVICE_SPECS, build_service_app
from nex_runtime.auth import issue_mock_service_token
from nex_runtime.service_token_admission import (
    AdmittedServiceClaims,
    HttpOaJwksSource,
    HttpOaTokenIntrospector,
    ServiceTokenAdmissionError,
    ServiceTokenAdmissionRuntime,
    build_service_token_admission_runtime,
)
from nex_runtime.signed_token_verifier import (
    BoundedJwksCache,
    SignedServiceTokenVerifier,
    SignedTokenVerificationError,
    StaticJwksSource,
)


REFERENCE = "memory://oa-key-admission"
KEY_ID = "oa-key-admission"


@pytest.fixture(scope="module")
def signing_runtime() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    return {
        "signer": signer,
        "jwk": signer.public_jwk(REFERENCE, key_id=KEY_ID),
    }


def _claims(**changes: Any) -> dict[str, Any]:
    claims = {
        "iss": "urn:nex-platform:oa",
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "iat": 500,
        "nbf": 500,
        "exp": 800,
        "jti": "sat-admission",
        "token_use": "service_access",
        "scope": "service:call document:read",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 3,
    }
    claims.update(changes)
    return claims


def _token(runtime: dict[str, Any], **claim_changes: Any) -> str:
    return encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims=_claims(**claim_changes),
        private_key_ref=REFERENCE,
        signing_provider=runtime["signer"],
    )


def _verifier(runtime: dict[str, Any]) -> SignedServiceTokenVerifier:
    source = StaticJwksSource(
        {"issuer": "urn:nex-platform:oa", "keys": [runtime["jwk"]]}
    )
    return SignedServiceTokenVerifier(
        BoundedJwksCache(source, clock=lambda: 600), clock=lambda: 600
    )


def _introspection(**changes: Any) -> dict[str, Any]:
    result = {
        "introspection_schema_version": "oa_token_introspection.v1",
        "active": True,
        "token_use": "service_access",
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "scope": "service:call document:read",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 3,
        "token_id_digest": sha256(b"sat-admission").hexdigest(),
        "iat": 500,
        "exp": 800,
    }
    result.update(changes)
    return result


class RecordingIntrospector:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "token": token,
                "expected_audience": expected_audience,
                "required_scopes": tuple(required_scopes),
            }
        )
        return self.result


def test_test_mock_profile_accepts_only_mock_tokens(
    signing_runtime: dict[str, Any],
) -> None:
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx", rollout_profile="TEST_MOCK", clock=lambda: 600
    )
    mock = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        scopes=["service:call"],
    )

    admitted = runtime.admit(
        f"Bearer {mock.access_token}", required_scopes=("service:call",)
    )

    assert admitted.token_kind == "MOCK"
    assert admitted.service_id == "nex-ae-api"
    assert admitted.to_wire()["scopes"] == ["service:call"]
    with pytest.raises(ServiceTokenAdmissionError) as signed:
        runtime.admit(f"Bearer {_token(signing_runtime)}")
    assert signed.value.error_code == "nex.signed_token_forbidden"


def test_signed_read_is_local_and_sensitive_route_is_introspected(
    signing_runtime: dict[str, Any],
) -> None:
    introspector = RecordingIntrospector(_introspection())
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=_verifier(signing_runtime),
        introspector=introspector,
        clock=lambda: 600,
    )
    token = _token(signing_runtime)

    local = runtime.admit(
        f"Bearer {token}", required_scopes=("document:read",), route_class="READ"
    )
    sensitive = runtime.admit(
        f"Bearer {token}", required_scopes=("service:call",), route_class="WRITE"
    )

    assert local.token_kind == "SIGNED"
    assert local.introspection_status == "NOT_REQUIRED"
    assert introspector.calls[0] == {
        "token": token,
        "expected_audience": "nex-cx",
        "required_scopes": ("service:call",),
    }
    assert sensitive.introspection_status == "ACTIVE"
    assert sensitive.token_id_digest == sha256(b"sat-admission").hexdigest()
    assert "jti" not in sensitive.to_wire()


@pytest.mark.parametrize("route_class", ["WRITE", "ADMIN", "CREDENTIAL", "KEY_MANAGEMENT"])
def test_every_sensitive_route_requires_introspection(
    signing_runtime: dict[str, Any], route_class: str
) -> None:
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=_verifier(signing_runtime),
        clock=lambda: 600,
    )
    with pytest.raises(ServiceTokenAdmissionError) as exc:
        runtime.admit(f"Bearer {_token(signing_runtime)}", route_class=route_class)
    assert exc.value.status_code == 503
    assert exc.value.retryable is True


@pytest.mark.parametrize(
    "change",
    [
        {"active": False, "reason_code": "oa.token_revoked"},
        {"token_id_digest": "0" * 64},
        {"credential_revision": 4},
        {"scope": "service:call"},
        {"introspection_schema_version": "wrong"},
    ],
)
def test_introspection_inactive_or_binding_mismatch_fails_closed(
    signing_runtime: dict[str, Any], change: dict[str, Any]
) -> None:
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=_verifier(signing_runtime),
        introspector=RecordingIntrospector(_introspection(**change)),
        clock=lambda: 600,
    )
    with pytest.raises(ServiceTokenAdmissionError) as exc:
        runtime.admit(f"Bearer {_token(signing_runtime)}", route_class="ADMIN")
    assert exc.value.status_code == 401
    assert exc.value.error_code in {
        "nex.token_introspection_inactive",
        "nex.token_introspection_binding_invalid",
    }


def test_dual_read_mock_allowlist_and_deadline_are_explicit() -> None:
    mock = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-cx", scopes=["service:call"]
    )
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="DUAL_READ",
        signed_verifier=object(),  # type: ignore[arg-type]
        legacy_mock_callers=("nex-ae-api",),
        compatibility_deadline_epoch=700,
        clock=lambda: 600,
    )
    admitted = runtime.admit(
        f"Bearer {mock.access_token}", route_class="WRITE", now_epoch=600
    )
    assert admitted.introspection_status == "LEGACY_NOT_APPLICABLE"

    runtime.legacy_mock_callers = ("nex-mo",)
    with pytest.raises(ServiceTokenAdmissionError) as caller:
        runtime.admit(f"Bearer {mock.access_token}", now_epoch=600)
    assert caller.value.error_code == "nex.mock_caller_forbidden"
    runtime.legacy_mock_callers = ("nex-ae-api",)
    with pytest.raises(ServiceTokenAdmissionError) as expired:
        runtime.admit(f"Bearer {mock.access_token}", now_epoch=701)
    assert expired.value.error_code == "nex.mock_compatibility_expired"


def test_mock_failures_and_signed_only_never_fall_back(
    signing_runtime: dict[str, Any],
) -> None:
    signed_only = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=_verifier(signing_runtime),
        clock=lambda: 600,
    )
    mock = issue_mock_service_token(service_id="nex-ae-api", audience="nex-mo")
    with pytest.raises(ServiceTokenAdmissionError) as forbidden:
        signed_only.admit(f"Bearer {mock.access_token}")
    assert forbidden.value.error_code == "nex.mock_token_forbidden"

    dual = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="DUAL_READ",
        signed_verifier=_verifier(signing_runtime),
        legacy_mock_callers=("nex-ae-api",),
        compatibility_deadline_epoch=700,
        clock=lambda: 600,
    )
    with pytest.raises(ServiceTokenAdmissionError) as audience:
        dual.admit(f"Bearer {mock.access_token}")
    assert audience.value.status_code == 403
    with pytest.raises(ServiceTokenAdmissionError) as malformed:
        dual.admit("Bearer definitely-not-a-mock-token")
    assert malformed.value.error_code == "nex.token_malformed"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rollout_profile": "UNKNOWN"},
        {"rollout_profile": "TEST_MOCK", "legacy_mock_callers": ("nex-ae-api",)},
        {"rollout_profile": "TEST_MOCK", "compatibility_deadline_epoch": 1},
        {"rollout_profile": "SIGNED_ONLY"},
        {
            "rollout_profile": "SIGNED_ONLY",
            "signed_verifier": object(),
            "legacy_mock_callers": ("nex-ae-api",),
        },
        {"rollout_profile": "DUAL_READ", "signed_verifier": object()},
        {
            "rollout_profile": "DUAL_READ",
            "signed_verifier": object(),
            "legacy_mock_callers": ("nex-ae-api",),
        },
    ],
)
def test_admission_configuration_rejects_unsafe_profiles(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ServiceTokenAdmissionRuntime(expected_audience="nex-cx", **kwargs)


def test_admission_inputs_are_strict(signing_runtime: dict[str, Any]) -> None:
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx", rollout_profile="TEST_MOCK"
    )
    for authorization, code in (
        (None, "nex.authorization_missing"),
        ("Basic value", "nex.authorization_invalid"),
        ("Bearer  value", "nex.authorization_invalid"),
    ):
        with pytest.raises(ServiceTokenAdmissionError) as exc:
            runtime.admit(authorization)
        assert exc.value.error_code == code
    with pytest.raises(ValueError):
        runtime.admit("Bearer value", route_class="UNKNOWN")
    with pytest.raises(ValueError):
        runtime.admit("Bearer value", required_scopes="scope")
    with pytest.raises(ValueError):
        runtime.admit("Bearer value", required_scopes=("scope", "scope"))
    with pytest.raises(ServiceTokenAdmissionError) as clock:
        runtime.admit("Bearer value", now_epoch=True)
    assert clock.value.error_code == "nex.token_clock_invalid"


def test_http_jwks_source_request_shape_and_failures(
    signing_runtime: dict[str, Any],
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def success(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append((method, url, kwargs))
        return httpx.Response(
            200,
            json={"issuer": "urn:nex-platform:oa", "keys": [signing_runtime["jwk"]]},
        )

    source = HttpOaJwksSource(base_url="http://oa.local/", requester=success)
    assert source.fetch_jwks()["issuer"] == "urn:nex-platform:oa"
    assert calls[0][0:2] == ("GET", "http://oa.local/.well-known/jwks.json")
    assert calls[0][2]["timeout"] == 3.0

    for requester, error_type, code in (
        (
            lambda *args, **kwargs: httpx.Response(503),
            SignedTokenVerificationError,
            "nex.jwks_unavailable",
        ),
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("private")),
            SignedTokenVerificationError,
            "nex.jwks_unavailable",
        ),
        (
            lambda *args, **kwargs: httpx.Response(200, content=b"not-json"),
            ServiceTokenAdmissionError,
            "nex.oa_auth_response_invalid",
        ),
        (
            lambda *args, **kwargs: httpx.Response(200, json=[]),
            ServiceTokenAdmissionError,
            "nex.oa_auth_response_invalid",
        ),
    ):
        with pytest.raises(error_type) as exc:
            HttpOaJwksSource(requester=requester).fetch_jwks()
        assert getattr(exc.value, "code", getattr(exc.value, "error_code", None)) == code


def test_http_introspector_request_shape_and_failures() -> None:
    calls: list[dict[str, Any]] = []

    def success(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json=_introspection())

    client = HttpOaTokenIntrospector(
        authorization_token="caller-token",
        base_url="http://oa.local/",
        requester=success,
    )
    assert "caller-token" not in repr(client)
    assert client.introspect(
        "target-token",
        expected_audience="nex-cx",
        required_scopes=("service:call",),
    )["active"] is True
    assert calls[0]["url"] == "http://oa.local/api/v1/auth/introspect"
    assert calls[0]["headers"]["Authorization"] == "Bearer caller-token"
    assert calls[0]["json"]["token"] == "target-token"

    for requester, retryable in (
        (lambda *args, **kwargs: httpx.Response(401), False),
        (lambda *args, **kwargs: httpx.Response(503), True),
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("private")),
            True,
        ),
    ):
        with pytest.raises(ServiceTokenAdmissionError) as exc:
            HttpOaTokenIntrospector(
                authorization_token="caller-token", requester=requester
            ).introspect(
                "target-token", expected_audience="nex-cx", required_scopes=()
            )
        assert exc.value.error_code == "nex.token_introspection_unavailable"
        assert exc.value.retryable is retryable


def test_http_client_and_builder_configuration_is_bounded() -> None:
    for factory, kwargs in (
        (HttpOaJwksSource, {"base_url": "ftp://oa.local"}),
        (HttpOaJwksSource, {"timeout_seconds": 0}),
        (HttpOaJwksSource, {"timeout_seconds": 11}),
        (HttpOaJwksSource, {"timeout_seconds": True}),
        (HttpOaJwksSource, {"requester": None}),
        (HttpOaTokenIntrospector, {"authorization_token": ""}),
        (
            HttpOaTokenIntrospector,
            {"authorization_token": "token", "requester": None},
        ),
    ):
        with pytest.raises((ValueError, TypeError)):
            factory(**kwargs)  # type: ignore[operator]

    mock = build_service_token_admission_runtime(
        expected_audience="nex-cx", environ={}
    )
    assert mock.rollout_profile == "TEST_MOCK"
    signed = build_service_token_admission_runtime(
        expected_audience="nex-cx",
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"},
    )
    assert signed.rollout_profile == "SIGNED_ONLY"
    assert signed.introspector is None
    dual = build_service_token_admission_runtime(
        expected_audience="nex-cx",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "dual_read",
            "NEX_LEGACY_MOCK_CALLERS": "nex-ae-api,nex-mo",
            "NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH": "700",
            "NEX_OA_INTROSPECTION_SERVICE_TOKEN": "caller-token",
            "NEX_OA_AUTH_TIMEOUT_SECONDS": "4.5",
        },
    )
    assert dual.legacy_mock_callers == ("nex-ae-api", "nex-mo")
    assert isinstance(dual.introspector, HttpOaTokenIntrospector)

    for environ in (
        {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ"},
        {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY", "NEX_OA_AUTH_TIMEOUT_SECONDS": "bad"},
        {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ", "NEX_LEGACY_MOCK_CALLERS": "nex-ae-api", "NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH": "bad"},
        {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ", "NEX_LEGACY_MOCK_CALLERS": "nex-ae-api", "NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH": "0"},
    ):
        with pytest.raises(ValueError):
            build_service_token_admission_runtime(
                expected_audience="nex-cx", environ=environ
            )


def test_constructor_rejects_invalid_clock_and_legacy_caller_collections() -> None:
    with pytest.raises(TypeError):
        ServiceTokenAdmissionRuntime(
            expected_audience="nex-cx",
            rollout_profile="TEST_MOCK",
            clock=None,  # type: ignore[arg-type]
        )
    for callers in ("nex-ae-api", ("nex-ae-api", "nex-ae-api")):
        with pytest.raises(ValueError):
            ServiceTokenAdmissionRuntime(
                expected_audience="nex-cx",
                rollout_profile="DUAL_READ",
                signed_verifier=object(),  # type: ignore[arg-type]
                legacy_mock_callers=callers,  # type: ignore[arg-type]
                compatibility_deadline_epoch=700,
            )


def test_fastapi_service_claim_route_uses_injected_admission_runtime() -> None:
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx", rollout_profile="TEST_MOCK"
    )
    client = TestClient(
        build_service_app(
            SERVICE_SPECS["nex-cx"], service_token_admission=runtime
        )
    )
    token = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-cx", scopes=["service:call"]
    ).access_token

    accepted = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {token}"},
    )
    rejected = client.get("/internal/v1/auth/service-claim")

    assert accepted.status_code == 200
    assert accepted.json()["claims"]["token_kind"] == "MOCK"
    assert rejected.status_code == 401
    assert rejected.json()["error_code"] == "nex.authorization_missing"


def test_admitted_claim_projection_omits_optional_signed_fields() -> None:
    claims = AdmittedServiceClaims(
        issuer="nex-oa",
        subject="service:nex-ae-api",
        audience="nex-cx",
        service_id="nex-ae-api",
        scopes=("service:call",),
        token_use="service",
        token_kind="MOCK",
        issued_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-01T01:00:00Z",
    )
    assert "credential_id" not in claims.to_wire()
    assert str(ServiceTokenAdmissionError(401, "code", "detail")) == "detail"
