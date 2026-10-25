from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime.demo_service_token_bootstrap import (
    DEMO_CLIENT_SECRET_ENV,
    DEMO_CREDENTIAL_ID_ENV,
    DemoServiceTokenBootstrapError,
    demo_startup_token_grants_for_owner,
    issue_demo_startup_service_tokens,
)
from nex_runtime.demo_trust import demo_secret_bindings_for_owner
from nex_runtime.production_container_bootstrap import (
    prepare_production_container_environment,
)
from nex_runtime.production_secret_materialization import ResolvedSecret


REFERENCE = "memory://p8-demo-startup-token"
KEY_ID = "p8-demo-startup-token"


def _environment(owner: str = "nex-eos") -> dict[str, str]:
    result = {
        "NEX_PROFILE": "staging_live",
        "NEX_DEPLOYMENT_BOUNDARY": "P8_DEMO",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        "NEX_P8_DEMO_SERVICE_TOKEN_PROFILE": "STARTUP_24H",
        "NEX_P8_DEMO_STARTUP_TOKEN_BOOTSTRAP": "true",
        "NEX_OA_BASE_URL": "https://oa.nex-staging.test:8443",
        "NEX_OPENBAO_TIMEOUT_SECONDS": "10",
        "NEX_SECRET_GENERATION": "secret:p8-demo.1",
        "NEX_OPENBAO_ROLE_ID_FILE": "/run/secrets/role",
        "NEX_OPENBAO_SECRET_ID_FILE": "/run/secrets/secret",
        DEMO_CREDENTIAL_ID_ENV: f"credential-{owner}",
        DEMO_CLIENT_SECRET_ENV: "private-client-secret",
    }
    return result


class TokenEndpoint:
    def __init__(self, owner: str = "nex-eos") -> None:
        self.signer = InMemoryOaRsaSigningProvider()
        self.signer.generate_key(REFERENCE)
        self.jwk = self.signer.public_jwk(REFERENCE, key_id=KEY_ID)
        self.owner = owner
        self.requests: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if method == "GET" and url.endswith("/.well-known/jwks.json"):
            return httpx.Response(
                200,
                json={"issuer": "urn:nex-platform:oa", "keys": [self.jwk]},
            )
        assert method == "POST"
        payload = dict(kwargs["json"])
        self.requests.append(payload)
        token = encode_signed_jwt(
            headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": f"service:{self.owner}",
                "aud": payload["audience"],
                "iat": 500,
                "nbf": 500,
                "exp": 86_900,
                "jti": f"demo-{len(self.requests)}",
                "token_use": "p8_demo_service_access",
                "scope": " ".join(sorted(payload["scope"].split(" "))),
                "service_id": self.owner,
                "credential_id": payload["credential_id"],
                "credential_revision": 1,
                "deployment_boundary": "P8_DEMO",
                "deployment_profile": "staging_live",
            },
            private_key_ref=REFERENCE,
            signing_provider=self.signer,
        )
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": 86_400,
                "scope": payload["scope"],
            },
        )


def test_startup_exchange_issues_audience_scoped_tokens_and_scrubs_credentials() -> None:
    endpoint = TokenEndpoint()
    environment, evidence = issue_demo_startup_service_tokens(
        "nex-eos",
        _environment(),
        requester=endpoint,
        clock=lambda: 500,
    )

    assert evidence.issued_token_count == 4
    assert evidence.token_ttl_seconds == 86_400
    assert evidence.raw_token_values_included is False
    assert evidence.credential_values_included is False
    assert DEMO_CREDENTIAL_ID_ENV not in environment
    assert DEMO_CLIENT_SECRET_ENV not in environment
    assert set(evidence.environment_names) == {
        "NEX_EOS_TO_WC_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
        "NEX_OA_INTROSPECTION_SERVICE_TOKEN",
    }
    assert all(environment[name].count(".") == 2 for name in evidence.environment_names)
    assert endpoint.requests[-1]["scope"] == "token:introspect"
    assert "private-client-secret" not in json.dumps(evidence.to_wire())

    oa_environment, oa_evidence = issue_demo_startup_service_tokens(
        "nex-oa", _environment("nex-oa"), requester=endpoint, clock=lambda: 500
    )
    assert oa_evidence.issued_token_count == 0
    assert oa_environment["NEX_PROFILE"] == "staging_live"


def test_bootstrap_profile_is_demo_only_and_fails_closed() -> None:
    endpoint = TokenEndpoint()
    for changes, message in (
        ({"NEX_PROFILE": "production"}, "NEX_PROFILE"),
        ({"NEX_DEPLOYMENT_BOUNDARY": "PRODUCTION"}, "boundary"),
        ({"NEX_P8_DEMO_SERVICE_TOKEN_PROFILE": "one-year"}, "PROFILE"),
        ({DEMO_CLIENT_SECRET_ENV: ""}, "credential"),
        ({"NEX_OA_BASE_URL": "http://oa"}, "HTTPS"),
        ({"NEX_OPENBAO_TIMEOUT_SECONDS": "31"}, "timeout"),
        ({"NEX_OPENBAO_TIMEOUT_SECONDS": "bad"}, "timeout"),
    ):
        with pytest.raises(DemoServiceTokenBootstrapError, match=message):
            issue_demo_startup_service_tokens(
                "nex-eos",
                {**_environment(), **changes},
                requester=endpoint,
                clock=lambda: 500,
            )
    with pytest.raises(DemoServiceTokenBootstrapError, match="owner"):
        demo_startup_token_grants_for_owner("unknown")
    with pytest.raises(DemoServiceTokenBootstrapError, match="owner"):
        issue_demo_startup_service_tokens("unknown", _environment())


def test_bootstrap_rejects_endpoint_failure_and_invalid_token_binding() -> None:
    def rejected(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(403, json={"detail": "private"})

    with pytest.raises(DemoServiceTokenBootstrapError, match="rejected") as error:
        issue_demo_startup_service_tokens(
            "nex-eos", _environment(), requester=rejected, clock=lambda: 500
        )
    assert "private" not in str(error.value)

    def unavailable(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError(
            "private endpoint", request=httpx.Request("POST", "https://oa")
        )

    with pytest.raises(DemoServiceTokenBootstrapError, match="unavailable"):
        issue_demo_startup_service_tokens(
            "nex-eos", _environment(), requester=unavailable, clock=lambda: 500
        )

    for response in (
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"access_token": "bad", "token_type": "Basic"}),
    ):
        def invalid(*args: Any, **kwargs: Any) -> httpx.Response:
            return response

        with pytest.raises(DemoServiceTokenBootstrapError, match="invalid"):
            issue_demo_startup_service_tokens(
                "nex-eos", _environment(), requester=invalid, clock=lambda: 500
            )

    endpoint = TokenEndpoint(owner="nex-wc")
    with pytest.raises(Exception):
        issue_demo_startup_service_tokens(
            "nex-eos", _environment(), requester=endpoint, clock=lambda: 500
        )

    endpoint = TokenEndpoint()
    original = endpoint.__call__

    def wrong_ttl(method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = original(method, url, **kwargs)
        if method == "POST":
            payload = response.json()
            payload["expires_in"] = 300
            return httpx.Response(200, json=payload)
        return response

    with pytest.raises(DemoServiceTokenBootstrapError, match="profile"):
        issue_demo_startup_service_tokens(
            "nex-eos", _environment(), requester=wrong_ttl, clock=lambda: 500
        )


class Resolver:
    def __init__(self) -> None:
        self.revoked = False

    def resolve(self, reference: str, *, context: Any) -> ResolvedSecret:
        return ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="openbao",
            value=f"private-{context.target_environment_name}",
        )

    def revoke(self) -> None:
        self.revoked = True


def test_production_container_bootstrap_materializes_credentials_then_invokes_exchange() -> None:
    environment = _environment()
    environment.pop(DEMO_CREDENTIAL_ID_ENV)
    environment.pop(DEMO_CLIENT_SECRET_ENV)
    for binding in (
        *demo_secret_bindings_for_owner("nex-eos"),
        *(
            type(demo_secret_bindings_for_owner("nex-eos")[0])(
                "nex-eos", target
            )
            for target in (DEMO_CREDENTIAL_ID_ENV, DEMO_CLIENT_SECRET_ENV)
        ),
    ):
        environment[binding.source_environment_name] = (
            "secret://openbao/nex-platform/staging/nex-eos/"
            f"{binding.target_environment_name}@v1"
        )
    captured: dict[str, Any] = {}

    def issuer(owner: str, values: Any):
        captured.update(owner=owner, values=dict(values))
        result = dict(values)
        result.pop(DEMO_CREDENTIAL_ID_ENV)
        result.pop(DEMO_CLIENT_SECRET_ENV)
        result["NEX_EOS_TO_AE_SERVICE_TOKEN"] = "issued-token"
        return result, object()

    resolver = Resolver()
    process_environment, materialization = prepare_production_container_environment(
        "nex-eos",
        environment,
        resolver_factory=lambda _: resolver,
        demo_token_issuer=issuer,
    )

    assert resolver.revoked is True
    assert captured["owner"] == "nex-eos"
    assert len(materialization.owner_environment.secrets) == 6
    assert process_environment["NEX_EOS_TO_AE_SERVICE_TOKEN"] == "issued-token"
    assert DEMO_CREDENTIAL_ID_ENV not in process_environment
    assert not any(name.endswith("_REF") for name in process_environment)
