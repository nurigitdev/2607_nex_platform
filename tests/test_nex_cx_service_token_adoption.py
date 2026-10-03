from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from nex_cx.authorization import authorize_cx_request
from nex_cx.embedding_index import EmbeddingIndexError, HttpMoEmbeddingClient
from nex_cx.generation import GenerationFacadeError, HttpMoGenerationClient
from nex_cx.retrieval import HttpMoRerankClient, RetrievalError
from nex_cx.service_auth import (
    CxOutboundServiceTokenError,
    resolve_cx_outbound_service_token,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
)


REFERENCE = "memory://oa-key-cx-adoption"
KEY_ID = "oa-key-cx-adoption"


@pytest.fixture(scope="module")
def signed_runtime() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-ae-api",
            "aud": "nex-cx",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-cx-adoption",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-ae-api",
            "credential_id": "cred-ae-runtime",
            "credential_revision": 1,
        },
        private_key_ref=REFERENCE,
        signing_provider=signer,
    )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(
                {
                    "issuer": "urn:nex-platform:oa",
                    "keys": [signer.public_jwk(REFERENCE, key_id=KEY_ID)],
                }
            ),
            clock=lambda: 600,
        ),
        clock=lambda: 600,
    )
    return {
        "token": token,
        "admission": ServiceTokenAdmissionRuntime(
            expected_audience="nex-cx",
            rollout_profile="SIGNED_ONLY",
            signed_verifier=verifier,
            clock=lambda: 600,
        ),
    }


def _client(admission: ServiceTokenAdmissionRuntime) -> TestClient:
    app = FastAPI()
    app.state.service_token_admission = admission

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_cx_request(request, authorization)
        if denied is not None:
            return denied
        return {
            "service_id": request.state.cx_caller_service_id,
            "scopes": list(request.state.cx_caller_scopes),
        }

    return TestClient(app)


def test_cx_central_guard_accepts_signed_service_token(
    signed_runtime: dict[str, Any],
) -> None:
    response = _client(signed_runtime["admission"]).get(
        "/guard",
        headers={"Authorization": f"Bearer {signed_runtime['token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "service_id": "nex-ae-api",
        "scopes": ["service:call"],
    }


def test_cx_signed_only_guard_rejects_mock_without_fallback(
    signed_runtime: dict[str, Any],
) -> None:
    mock = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    response = _client(signed_runtime["admission"]).get(
        "/guard", headers={"Authorization": f"Bearer {mock.access_token}"}
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "nex.mock_token_forbidden"


def test_cx_outbound_token_resolution_is_profile_driven() -> None:
    assert resolve_cx_outbound_service_token(
        "signed-token", audience="nex-mo", environ={}
    ) == "signed-token"
    assert resolve_cx_outbound_service_token(
        None,
        audience="nex-mo",
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
    ).startswith("nex-mock-service.")
    assert resolve_cx_outbound_service_token(
        None,
        audience="nex-mo",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_CX_TO_MO_SERVICE_TOKEN": "signed-from-env",
        },
    ) == "signed-from-env"

    for configured, audience, environ, code in (
        (" bad ", "nex-mo", {}, "cx.outbound_service_token_invalid"),
        (None, "nex-mo", {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"}, "cx.outbound_service_token_missing"),
        (None, "nex-mo", {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "wrong"}, "cx.service_token_rollout_profile_invalid"),
        (None, "external", {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ"}, "cx.outbound_service_token_missing"),
    ):
        with pytest.raises(CxOutboundServiceTokenError) as exc:
            resolve_cx_outbound_service_token(
                configured, audience=audience, environ=environ
            )
        assert exc.value.error_code == code
        assert str(exc.value) == exc.value.detail


def test_cx_provider_clients_fail_closed_without_signed_outbound_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    monkeypatch.delenv("NEX_CX_TO_MO_SERVICE_TOKEN", raising=False)

    with pytest.raises(EmbeddingIndexError) as embedding:
        HttpMoEmbeddingClient().create_embeddings(
            ["text"], alias="embedding", request_id="req", trace_id="a" * 32
        )
    with pytest.raises(GenerationFacadeError) as generation:
        HttpMoGenerationClient().create_generation(
            {"prompt": "text"}, request_id="req", trace_id="a" * 32
        )
    with pytest.raises(RetrievalError) as rerank:
        HttpMoRerankClient().rerank_documents(
            "query",
            ["text"],
            alias="reranker",
            top_n=1,
            request_id="req",
            trace_id="a" * 32,
        )

    assert {
        embedding.value.error_code,
        generation.value.error_code,
        rerank.value.error_code,
    } == {"cx.outbound_service_token_missing"}
