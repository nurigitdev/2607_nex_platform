from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
import httpx

from nex_oa.auth_events import (
    OaAuthEventRepository,
    auth_event_target,
    record_auth_event_safely,
)
from nex_oa.federated_identities import (
    OaFederationError,
    resolve_federated_identity,
)
from nex_oa.federated_identity_repository import OaFederatedIdentityRepository
from nex_oa.oidc_verifier import (
    OidcDiscoveryJwksCache,
    OidcDocumentSource,
    OidcIdTokenVerifier,
    VerifiedOidcIdentity,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_FEDERATED_LOGIN_RESPONSE_SCHEMA_VERSION = "oa_federated_login_response.v1"
FEDERATED_LOGIN_FIELDS = frozenset(
    {"provider_id", "id_token", "nonce", "requested_scopes", "ttl_seconds"}
)
MAX_OIDC_DOCUMENT_BYTES = 65_536
OIDC_HTTP_TIMEOUT_SECONDS = 5.0


class OaFederatedSessionIssuer(Protocol):
    def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


class OaOidcVerifierProvider(Protocol):
    def for_provider(self, provider: Mapping[str, Any]) -> OidcIdTokenVerifier: ...


@dataclass
class HttpOidcDocumentSource:
    requester: Callable[..., httpx.Response] = httpx.get
    timeout_seconds: float = OIDC_HTTP_TIMEOUT_SECONDS
    max_document_bytes: int = MAX_OIDC_DOCUMENT_BYTES

    def fetch_json(self, url: str) -> Mapping[str, Any]:
        try:
            response = self.requester(
                url,
                timeout=self.timeout_seconds,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise _unavailable("OIDC provider document is unavailable.") from exc
        if response.status_code != 200:
            raise _unavailable("OIDC provider document returned an error.")
        if len(response.content) > self.max_document_bytes:
            raise _unavailable("OIDC provider document is too large.")
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise _unavailable("OIDC provider document is invalid.") from exc
        if not isinstance(payload, Mapping):
            raise _unavailable("OIDC provider document is invalid.")
        return payload


@dataclass
class CachingOidcVerifierProvider:
    source: OidcDocumentSource
    cache_ttl_seconds: int = 300
    _verifiers: dict[tuple[str, int], OidcIdTokenVerifier] = field(
        default_factory=dict
    )

    def for_provider(self, provider: Mapping[str, Any]) -> OidcIdTokenVerifier:
        key = (str(provider.get("provider_id") or ""), int(provider.get("revision") or 0))
        verifier = self._verifiers.get(key)
        if verifier is None:
            cache = OidcDiscoveryJwksCache(
                provider,
                self.source,
                ttl_seconds=self.cache_ttl_seconds,
            )
            verifier = OidcIdTokenVerifier(provider, cache)
            self._verifiers = {
                stored_key: stored
                for stored_key, stored in self._verifiers.items()
                if stored_key[0] != key[0]
            }
            self._verifiers[key] = verifier
        return verifier


@dataclass
class OaFederatedLoginService:
    repository: OaFederatedIdentityRepository
    session_issuer: OaFederatedSessionIssuer
    verifier_provider: OaOidcVerifierProvider

    def login(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = normalize_federated_login_request(payload)
        provider = self.repository.get_provider(request["provider_id"])
        if provider is None or provider.get("status") != "ACTIVE":
            raise OaFederationError(
                401,
                "oa.federated_login_provider_invalid",
                "Federated login provider is invalid.",
            )
        verified = self.verifier_provider.for_provider(provider).verify(
            request["id_token"],
            expected_nonce=request["nonce"],
        )
        identity = self.repository.find_identity(
            provider_id=provider["provider_id"],
            external_subject_digest=verified.external_subject_digest,
        )
        if identity is None:
            raise OaFederationError(
                403,
                "oa.federated_identity_not_linked",
                "Federated identity is not linked to an active OA subject.",
            )
        resolution = resolve_federated_identity(
            {
                "issuer": verified.issuer,
                "audience": verified.audiences,
                "subject": verified.external_subject,
            },
            provider=provider,
            identity_link=identity,
        )
        session_payload: dict[str, Any] = {
            "tenant_id": resolution["tenant_id"],
            "subject_id": resolution["subject_id"],
        }
        for name in ("requested_scopes", "ttl_seconds"):
            if name in request:
                session_payload[name] = deepcopy(request[name])
        session = self.session_issuer.issue_session(session_payload)
        return build_federated_login_response(
            session,
            provider_id=provider["provider_id"],
        )


def normalize_federated_login_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise OaFederationError(
            400,
            "oa.federated_login_payload_invalid",
            "Federated login request must be an object.",
        )
    unsupported = sorted(str(key) for key in payload if key not in FEDERATED_LOGIN_FIELDS)
    if unsupported:
        raise OaFederationError(
            400,
            "oa.federated_login_field_unsupported",
            "Federated login request contains an unsupported field.",
        )
    normalized = {
        name: deepcopy(payload[name])
        for name in FEDERATED_LOGIN_FIELDS
        if name in payload
    }
    for name in ("provider_id", "id_token", "nonce"):
        value = normalized.get(name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise OaFederationError(
                400,
                f"oa.federated_login_{name}_invalid",
                f"Federated login {name} is invalid.",
            )
    return normalized


def build_federated_login_response(
    session: Mapping[str, Any], *, provider_id: str
) -> dict[str, Any]:
    response = deepcopy(dict(session))
    metadata = response.get("metadata")
    safe_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    response["login_response_schema_version"] = (
        OA_FEDERATED_LOGIN_RESPONSE_SCHEMA_VERSION
    )
    response["metadata"] = {
        **safe_metadata,
        "auth_method": "federated_oidc",
        "provider_id": provider_id,
        "identity_link_verified": True,
        "raw_id_token_included": False,
        "raw_external_subject_included": False,
        "external_profile_included": False,
    }
    response["operator_context"] = build_federated_operator_context(session)
    return response


def build_federated_operator_context(
    session_issue: Mapping[str, Any],
) -> dict[str, Any]:
    session = session_issue.get("session")
    snapshot = session if isinstance(session, Mapping) else session_issue
    tenant_id = _context_ref_id(
        snapshot.get("tenant_ref", session_issue.get("tenant_ref")),
        fallback=snapshot.get("tenant_id", session_issue.get("tenant_id")),
        field="tenant_id",
    )
    subject_id = _context_ref_id(
        snapshot.get("subject_ref", session_issue.get("subject_ref")),
        fallback=snapshot.get("subject_id", session_issue.get("subject_id")),
        field="subject_id",
    )
    roles = _context_string_list(snapshot.get("roles"), field="roles")
    scopes = _context_string_list(snapshot.get("scopes"), field="scopes")
    session_id = _context_text(snapshot.get("session_id"), field="session_id")
    return {
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "roles": roles,
        "scopes": scopes,
        "auth_method": "federated_oidc",
        "session_id_digest": sha256(
            f"nex-oa-session:{session_id}".encode("utf-8")
        ).hexdigest(),
    }


def register_federated_login_routes(
    app: FastAPI,
    *,
    service: OaFederatedLoginService,
    auth_event_repository: OaAuthEventRepository | None = None,
) -> None:
    @app.post("/internal/v1/auth/federated-login", response_model=None)
    def federated_login(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_federated_login(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = service.login(payload)
        except OaFederationError as exc:
            record_auth_event_safely(
                auth_event_repository,
                event_type="FEDERATED_LOGIN_FAILED",
                outcome="BLOCKED" if exc.status_code in {401, 403} else "FAILED",
                request=request,
                authorization=authorization,
                details={
                    "error_code": exc.error_code,
                    "provider_id": _safe_provider_id(payload.get("provider_id")),
                },
            )
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Federated authentication failed",
                detail=exc.detail,
                type_uri="https://nex-platform.local/problems/federated-authentication-failed",
            )
        target = auth_event_target(response)
        record_auth_event_safely(
            auth_event_repository,
            event_type="FEDERATED_LOGIN_SUCCEEDED",
            outcome="SUCCEEDED",
            request=request,
            authorization=authorization,
            **target,
            details={
                "auth_method": "federated_oidc",
                "provider_id": response.get("metadata", {}).get("provider_id"),
            },
        )
        return {
            **response,
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
        }


def _authorize_federated_login(
    request: Request, authorization: str | None
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if result.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "OA requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _safe_provider_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    return value


def _context_ref_id(value: object, *, fallback: object, field: str) -> str:
    candidate = value.get("id") if isinstance(value, Mapping) else fallback
    return _context_text(candidate, field=field)


def _context_text(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
    ):
        raise OaFederationError(
            503,
            "oa.federated_session_projection_invalid",
            f"Federated session {field} projection is invalid.",
        )
    return value


def _context_string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise OaFederationError(
            503,
            "oa.federated_session_projection_invalid",
            f"Federated session {field} projection is invalid.",
        )
    normalized = [_context_text(item, field=field) for item in value]
    if len(normalized) != len(set(normalized)):
        raise OaFederationError(
            503,
            "oa.federated_session_projection_invalid",
            f"Federated session {field} projection is invalid.",
        )
    return normalized


def _unavailable(detail: str) -> OaFederationError:
    return OaFederationError(503, "oa.oidc_document_unavailable", detail)
