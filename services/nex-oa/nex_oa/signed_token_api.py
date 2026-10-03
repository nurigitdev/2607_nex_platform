from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_oa.service_principals import OaServicePrincipalError
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService
from nex_oa.token_validation_service import OaSignedTokenValidationService
from nex_runtime import (
    OperationalEventEmitter,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)


OA_INTROSPECTION_SCOPE = "token:introspect"
OA_REVOCATION_SCOPE = "token:revoke"
_TOKEN_FIELDS = frozenset(
    {"grant_type", "credential_id", "client_secret", "audience", "scope"}
)
_INTROSPECTION_FIELDS = frozenset({"token", "audience", "required_scopes"})
_REVOCATION_FIELDS = frozenset({"token", "audience", "reason_code"})


def register_signed_token_routes(
    app: FastAPI,
    *,
    token_exchange_service: OaClientCredentialTokenExchangeService,
    validation_service: OaSignedTokenValidationService,
    signing_key_service: OaSigningKeyService,
    audit_emitter: OperationalEventEmitter,
) -> None:
    @app.get("/.well-known/jwks.json", response_model=None)
    def get_jwks(request: Request):
        return _with_context(signing_key_service.jwks(), request)

    @app.post("/api/v1/auth/service-token", response_model=None)
    def exchange_service_token(payload: dict[str, Any], request: Request):
        try:
            body = _payload(
                payload,
                allowed=_TOKEN_FIELDS,
                required=(
                    "grant_type",
                    "credential_id",
                    "client_secret",
                    "audience",
                    "scope",
                ),
            )
            result = token_exchange_service.exchange(body)
        except (OaSignedTokenError, OaServicePrincipalError) as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_ACCESS_TOKEN_ISSUED",
            subject_id=str(body["credential_id"]),
            details={"audience": body["audience"], "scope": body["scope"]},
        )

    @app.post("/api/v1/auth/introspect", response_model=None)
    def introspect_service_token(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(
            request,
            authorization,
            validation_service=validation_service,
            required_scope=OA_INTROSPECTION_SCOPE,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            body = _payload(
                payload,
                allowed=_INTROSPECTION_FIELDS,
                required=("token", "audience"),
            )
            required_scopes = body.get("required_scopes", [])
            if not isinstance(required_scopes, list):
                raise OaSignedTokenError(
                    "oa.token_request_invalid",
                    "required_scopes must be an array",
                    400,
                )
            result = validation_service.introspect(
                body["token"],
                expected_audience=body["audience"],
                required_scopes=required_scopes,
            )
        except (OaSignedTokenError, OaServicePrincipalError) as exc:
            return _problem(request, exc)
        return _with_context(result, request)

    @app.post("/api/v1/auth/revoke", response_model=None)
    def revoke_service_token(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(
            request,
            authorization,
            validation_service=validation_service,
            required_scope=OA_REVOCATION_SCOPE,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            body = _payload(
                payload,
                allowed=_REVOCATION_FIELDS,
                required=("token", "audience", "reason_code"),
            )
            claims = validation_service.validate(
                body["token"], expected_audience=body["audience"]
            )
            result = signing_key_service.revoke_token_claims(
                claims,
                reason_code=body["reason_code"],
            )
        except (OaSignedTokenError, OaServicePrincipalError) as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_ACCESS_TOKEN_REVOKED",
            subject_id=result["revocation_id"],
            details={"reason_code": result["reason_code"]},
        )


def _authorize(
    request: Request,
    authorization: str | None,
    *,
    validation_service: OaSignedTokenValidationService,
    required_scope: str,
) -> JSONResponse | None:
    try:
        token = _bearer_token(authorization)
        validation_service.validate(
            token,
            expected_audience="nex-oa",
            required_scopes=(required_scope,),
        )
    except (OaSignedTokenError, OaServicePrincipalError) as exc:
        return _problem(request, exc)
    return None


def _bearer_token(authorization: object) -> str:
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise OaSignedTokenError(
            "oa.bearer_token_missing", "Bearer authorization is required", 401
        )
    token = authorization[7:]
    if not token or token != token.strip():
        raise OaSignedTokenError(
            "oa.bearer_token_invalid", "Bearer authorization is invalid", 401
        )
    return token


def _payload(
    payload: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    required: tuple[str, ...],
) -> dict[str, Any]:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise OaSignedTokenError(
            "oa.token_request_invalid", f"unsupported field: {unexpected[0]}", 400
        )
    missing = [name for name in required if name not in payload]
    if missing:
        raise OaSignedTokenError(
            "oa.token_request_invalid", f"required field is missing: {missing[0]}", 400
        )
    return dict(payload)


def _with_context(result: Mapping[str, Any], request: Request) -> dict[str, Any]:
    return {
        **result,
        "request_id": request_id_from_headers(request),
        "trace_id": trace_id_from_headers(request),
    }


def _with_audit(
    result: Mapping[str, Any],
    *,
    request: Request,
    emitter: OperationalEventEmitter,
    event_type: str,
    subject_id: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    request_id = request_id_from_headers(request)
    trace_id = trace_id_from_headers(request)
    audit = emitter.safe_emit(
        event_type=event_type,
        severity="INFO",
        message="OA signed-token lifecycle mutation",
        request_id=request_id,
        trace_id=trace_id,
        subject_ref={"type": "oa.signed_token_lifecycle", "id": subject_id},
        details=dict(details),
    )
    return {
        **result,
        "request_id": request_id,
        "trace_id": trace_id,
        "audit_event": audit.to_summary(),
    }


def _problem(
    request: Request,
    exc: OaSignedTokenError | OaServicePrincipalError,
) -> JSONResponse:
    status_code = exc.status_code
    error_code = getattr(exc, "code", None) or getattr(exc, "error_code")
    detail = getattr(exc, "message", None) or getattr(exc, "detail")
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="Signed-token lifecycle request failed",
        detail=detail,
        type_uri="https://nex-platform.local/problems/signed-token-lifecycle",
    )
