from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from time import time
from typing import Any, Protocol

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from .auth import (
    MOCK_SERVICE_TOKEN_PREFIX,
    ServiceClaims,
    validate_authorization_header,
)
from .problem import problem_response
from .signed_token_verifier import (
    BoundedJwksCache,
    JwksSource,
    SignedServiceTokenVerifier,
    SignedTokenVerificationError,
    VerifiedServiceTokenClaims,
)


TOKEN_ROLLOUT_PROFILES = ("TEST_MOCK", "DUAL_READ", "SIGNED_ONLY")
TOKEN_ROUTE_CLASSES = ("READ", "WRITE", "ADMIN", "CREDENTIAL", "KEY_MANAGEMENT")
INTROSPECTION_ROUTE_CLASSES = frozenset(
    {"WRITE", "ADMIN", "CREDENTIAL", "KEY_MANAGEMENT"}
)
DEFAULT_OA_BASE_URL = "http://127.0.0.1:8101"
DEFAULT_OA_AUTH_TIMEOUT_SECONDS = 3.0
MAX_OA_AUTH_TIMEOUT_SECONDS = 10.0


@dataclass
class ServiceTokenAdmissionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AdmittedServiceClaims:
    issuer: str
    subject: str
    audience: str
    service_id: str
    scopes: tuple[str, ...]
    token_use: str
    token_kind: str
    issued_at: int | str
    expires_at: int | str
    credential_id: str | None = None
    credential_revision: int | None = None
    key_id: str | None = None
    token_id_digest: str | None = None
    introspection_status: str = "NOT_REQUIRED"

    def to_wire(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scopes"] = list(self.scopes)
        return {name: value for name, value in payload.items() if value is not None}


class TokenIntrospector(Protocol):
    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> Mapping[str, Any]: ...


HttpRequester = Callable[..., httpx.Response]


@dataclass(frozen=True)
class HttpOaJwksSource(JwksSource):
    base_url: str = DEFAULT_OA_BASE_URL
    timeout_seconds: float = DEFAULT_OA_AUTH_TIMEOUT_SECONDS
    requester: HttpRequester = httpx.request

    def __post_init__(self) -> None:
        _base_url(self.base_url)
        _timeout(self.timeout_seconds)
        if not callable(self.requester):
            raise TypeError("JWKS requester must be callable")

    def fetch_jwks(self) -> Mapping[str, Any]:
        try:
            response = self.requester(
                "GET",
                f"{self.base_url.rstrip('/')}/.well-known/jwks.json",
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise SignedTokenVerificationError(
                "nex.jwks_unavailable", "JWKS endpoint is unavailable", 503
            ) from exc
        if response.status_code >= 400:
            raise SignedTokenVerificationError(
                "nex.jwks_unavailable", "JWKS endpoint rejected the request", 503
            )
        payload = _response_object(response, "JWKS")
        return payload


@dataclass(frozen=True)
class HttpOaTokenIntrospector(TokenIntrospector):
    authorization_token: str = field(repr=False)
    base_url: str = DEFAULT_OA_BASE_URL
    timeout_seconds: float = DEFAULT_OA_AUTH_TIMEOUT_SECONDS
    requester: HttpRequester = httpx.request

    def __post_init__(self) -> None:
        _secret_token(self.authorization_token, "introspection authorization token")
        _base_url(self.base_url)
        _timeout(self.timeout_seconds)
        if not callable(self.requester):
            raise TypeError("introspection requester must be callable")

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> Mapping[str, Any]:
        target = _secret_token(token, "target token")
        audience = _nonempty_string(expected_audience, "expected audience")
        scopes = _scope_sequence(required_scopes)
        try:
            response = self.requester(
                "POST",
                f"{self.base_url.rstrip('/')}/api/v1/auth/introspect",
                json={
                    "token": target,
                    "audience": audience,
                    "required_scopes": list(scopes),
                },
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.authorization_token}",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ServiceTokenAdmissionError(
                503,
                "nex.token_introspection_unavailable",
                "OA token introspection is unavailable",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise ServiceTokenAdmissionError(
                503,
                "nex.token_introspection_unavailable",
                "OA token introspection rejected the request",
                retryable=response.status_code >= 500,
            )
        return _response_object(response, "introspection")


class ServiceTokenAdmissionRuntime:
    def __init__(
        self,
        *,
        expected_audience: str,
        rollout_profile: str,
        signed_verifier: SignedServiceTokenVerifier | None = None,
        introspector: TokenIntrospector | None = None,
        legacy_mock_callers: Sequence[str] = (),
        compatibility_deadline_epoch: int | None = None,
        clock: Callable[[], float] = time,
    ) -> None:
        self.expected_audience = _nonempty_string(
            expected_audience, "expected audience"
        )
        if rollout_profile not in TOKEN_ROLLOUT_PROFILES:
            raise ValueError("unsupported service-token rollout profile")
        if not callable(clock):
            raise TypeError("service-token admission clock must be callable")
        callers = _service_ids(legacy_mock_callers)
        if rollout_profile == "TEST_MOCK":
            if signed_verifier is not None or introspector is not None or callers:
                raise ValueError("TEST_MOCK cannot configure signed-token controls")
            if compatibility_deadline_epoch is not None:
                raise ValueError("TEST_MOCK cannot configure a compatibility deadline")
        elif signed_verifier is None:
            raise ValueError("signed verifier is required for signed-token profiles")
        if rollout_profile == "DUAL_READ":
            if not callers:
                raise ValueError("DUAL_READ requires legacy mock callers")
            if not _positive_integer(compatibility_deadline_epoch):
                raise ValueError("DUAL_READ requires a compatibility deadline")
        elif callers or compatibility_deadline_epoch is not None:
            raise ValueError("legacy mock controls are allowed only in DUAL_READ")
        self.rollout_profile = rollout_profile
        self.signed_verifier = signed_verifier
        self.introspector = introspector
        self.legacy_mock_callers = callers
        self.compatibility_deadline_epoch = compatibility_deadline_epoch
        self._clock = clock

    def admit(
        self,
        authorization: object,
        *,
        required_scopes: Sequence[str] = (),
        route_class: str = "READ",
        now_epoch: int | None = None,
    ) -> AdmittedServiceClaims:
        route = _route_class(route_class)
        scopes = _scope_sequence(required_scopes)
        token = _bearer_token(authorization)
        now = self._now(now_epoch)
        is_mock = token.startswith(MOCK_SERVICE_TOKEN_PREFIX)
        if is_mock:
            return self._admit_mock(
                authorization,
                required_scopes=scopes,
                route_class=route,
                now_epoch=now,
            )
        return self._admit_signed(
            authorization,
            token=token,
            required_scopes=scopes,
            route_class=route,
            now_epoch=now,
        )

    def _admit_mock(
        self,
        authorization: object,
        *,
        required_scopes: tuple[str, ...],
        route_class: str,
        now_epoch: int,
    ) -> AdmittedServiceClaims:
        if self.rollout_profile == "SIGNED_ONLY":
            raise _unauthorized(
                "nex.mock_token_forbidden", "mock service tokens are not accepted"
            )
        admitted = admit_test_mock_service_token(
            authorization,
            expected_audience=self.expected_audience,
            required_scopes=required_scopes,
            route_class=route_class,
            rollout_profile=self.rollout_profile,
        )
        if self.rollout_profile == "DUAL_READ":
            assert self.compatibility_deadline_epoch is not None
            if now_epoch > self.compatibility_deadline_epoch:
                raise _unauthorized(
                    "nex.mock_compatibility_expired",
                    "mock service-token compatibility has expired",
                )
            if admitted.service_id not in self.legacy_mock_callers:
                raise _forbidden(
                    "nex.mock_caller_forbidden", "mock service-token caller is forbidden"
                )
        return admitted

    def _admit_signed(
        self,
        authorization: object,
        *,
        token: str,
        required_scopes: tuple[str, ...],
        route_class: str,
        now_epoch: int,
    ) -> AdmittedServiceClaims:
        if self.rollout_profile == "TEST_MOCK":
            raise _unauthorized(
                "nex.signed_token_forbidden",
                "signed service tokens are not accepted in TEST_MOCK",
            )
        assert self.signed_verifier is not None
        try:
            claims = self.signed_verifier.verify_authorization_header(
                authorization,
                expected_audience=self.expected_audience,
                required_scopes=required_scopes,
                now_epoch=now_epoch,
            )
        except SignedTokenVerificationError as exc:
            raise ServiceTokenAdmissionError(
                exc.status_code,
                exc.code,
                exc.message,
                retryable=exc.status_code >= 500,
            ) from exc
        introspection_status = "NOT_REQUIRED"
        if route_class in INTROSPECTION_ROUTE_CLASSES:
            if self.introspector is None:
                raise ServiceTokenAdmissionError(
                    503,
                    "nex.token_introspection_unavailable",
                    "OA token introspection is required",
                    retryable=True,
                )
            result = self.introspector.introspect(
                token,
                expected_audience=self.expected_audience,
                required_scopes=required_scopes,
            )
            _validate_introspection_binding(result, claims)
            introspection_status = "ACTIVE"
        return _signed_projection(claims, introspection_status=introspection_status)

    def _now(self, now_epoch: int | None) -> int:
        value = int(self._clock()) if now_epoch is None else now_epoch
        if not _nonnegative_integer(value):
            raise _unauthorized("nex.token_clock_invalid", "validation clock is invalid")
        return int(value)


def build_service_token_admission_runtime(
    *,
    expected_audience: str,
    environ: Mapping[str, str] | None = None,
    requester: HttpRequester = httpx.request,
    clock: Callable[[], float] = time,
) -> ServiceTokenAdmissionRuntime:
    env = os.environ if environ is None else environ
    profile = env.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK").strip().upper()
    if profile == "TEST_MOCK":
        return ServiceTokenAdmissionRuntime(
            expected_audience=expected_audience,
            rollout_profile=profile,
            clock=clock,
        )
    base_url = env.get("NEX_OA_BASE_URL", DEFAULT_OA_BASE_URL)
    timeout = _timeout_env(env)
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            HttpOaJwksSource(
                base_url=base_url,
                timeout_seconds=timeout,
                requester=requester,
            ),
            clock=clock,
        ),
        clock=clock,
    )
    authorization_token = env.get("NEX_OA_INTROSPECTION_SERVICE_TOKEN")
    introspector = (
        HttpOaTokenIntrospector(
            authorization_token=authorization_token,
            base_url=base_url,
            timeout_seconds=timeout,
            requester=requester,
        )
        if authorization_token
        else None
    )
    callers = tuple(
        item.strip()
        for item in env.get("NEX_LEGACY_MOCK_CALLERS", "").split(",")
        if item.strip()
    )
    deadline = _optional_integer_env(env, "NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH")
    return ServiceTokenAdmissionRuntime(
        expected_audience=expected_audience,
        rollout_profile=profile,
        signed_verifier=verifier,
        introspector=introspector,
        legacy_mock_callers=callers,
        compatibility_deadline_epoch=deadline,
        clock=clock,
    )


def service_token_admission_problem_response(
    request: Request, exc: ServiceTokenAdmissionError
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Service-token admission failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/service-token-admission",
        retryable=exc.retryable,
    )


def admit_service_token_from_request(
    request: Request,
    authorization: object,
    *,
    expected_audience: str,
    required_scopes: Sequence[str],
    route_class: str = "READ",
) -> AdmittedServiceClaims | JSONResponse:
    runtime = getattr(request.app.state, "service_token_admission", None)
    if runtime is not None:
        if not isinstance(runtime, ServiceTokenAdmissionRuntime):
            return service_token_admission_problem_response(
                request,
                ServiceTokenAdmissionError(
                    503,
                    "nex.service_token_admission_unavailable",
                    "service-token admission runtime is unavailable",
                    retryable=True,
                ),
            )
        try:
            return runtime.admit(
                authorization,
                required_scopes=required_scopes,
                route_class=route_class,
            )
        except ServiceTokenAdmissionError as exc:
            return service_token_admission_problem_response(request, exc)
    result = validate_authorization_header(
        authorization if isinstance(authorization, str) else None,
        expected_audience=expected_audience,
        required_scopes=tuple(required_scopes),
    )
    if result.ok and result.claims is not None:
        return _mock_projection(
            result.claims,
            route_class=_route_class(route_class),
            profile="TEST_MOCK",
        )
    return service_token_admission_problem_response(
        request,
        ServiceTokenAdmissionError(
            401,
            result.error_code or "SERVICE_CLAIM_INVALID",
            result.detail or "Service claim validation failed.",
        ),
    )


def admit_test_mock_service_token(
    authorization: object,
    *,
    expected_audience: str,
    required_scopes: Sequence[str] = (),
    route_class: str = "READ",
    rollout_profile: str = "TEST_MOCK",
    now: datetime | None = None,
) -> AdmittedServiceClaims:
    profile = str(rollout_profile).strip().upper()
    if profile not in {"TEST_MOCK", "DUAL_READ"}:
        raise ValueError("mock admission requires TEST_MOCK or DUAL_READ profile")
    route = _route_class(route_class)
    scopes = _scope_sequence(required_scopes)
    result = validate_authorization_header(
        authorization if isinstance(authorization, str) else None,
        expected_audience=_nonempty_string(expected_audience, "expected audience"),
        required_scopes=scopes,
        now=now,
    )
    if not result.ok or result.claims is None:
        status = (
            403
            if result.error_code in {"TOKEN_AUDIENCE_INVALID", "TOKEN_SCOPE_MISSING"}
            else 401
        )
        raise ServiceTokenAdmissionError(
            status,
            f"nex.mock_{str(result.error_code or 'token_invalid').lower()}",
            "mock service token validation failed",
        )
    return _mock_projection(
        result.claims,
        route_class=route,
        profile=profile,
    )


def _validate_introspection_binding(
    result: Mapping[str, Any], claims: VerifiedServiceTokenClaims
) -> None:
    if result.get("active") is not True:
        raise _unauthorized(
            "nex.token_introspection_inactive", "access token is inactive"
        )
    expected = {
        "introspection_schema_version": "oa_token_introspection.v1",
        "token_use": "service_access",
        "sub": claims.subject,
        "aud": claims.audience,
        "scope": " ".join(claims.scopes),
        "service_id": claims.service_id,
        "credential_id": claims.credential_id,
        "credential_revision": claims.credential_revision,
        "iat": claims.issued_at,
        "exp": claims.expires_at,
        "token_id_digest": claims.token_id_digest,
    }
    if any(result.get(name) != value for name, value in expected.items()):
        raise _unauthorized(
            "nex.token_introspection_binding_invalid",
            "access token introspection binding is invalid",
        )


def _mock_projection(
    claims: ServiceClaims, *, route_class: str, profile: str
) -> AdmittedServiceClaims:
    return AdmittedServiceClaims(
        issuer=claims.issuer,
        subject=claims.subject,
        audience=claims.audience,
        service_id=claims.service_id,
        scopes=claims.scopes,
        token_use=claims.token_use,
        token_kind="MOCK",
        issued_at=claims.issued_at,
        expires_at=claims.expires_at,
        introspection_status=(
            "LEGACY_NOT_APPLICABLE"
            if profile == "DUAL_READ" and route_class in INTROSPECTION_ROUTE_CLASSES
            else "NOT_REQUIRED"
        ),
    )


def _signed_projection(
    claims: VerifiedServiceTokenClaims, *, introspection_status: str
) -> AdmittedServiceClaims:
    return AdmittedServiceClaims(
        issuer=claims.issuer,
        subject=claims.subject,
        audience=claims.audience,
        service_id=claims.service_id,
        scopes=claims.scopes,
        token_use="service_access",
        token_kind="SIGNED",
        issued_at=claims.issued_at,
        expires_at=claims.expires_at,
        credential_id=claims.credential_id,
        credential_revision=claims.credential_revision,
        key_id=claims.key_id,
        token_id_digest=claims.token_id_digest,
        introspection_status=introspection_status,
    )


def _bearer_token(authorization: object) -> str:
    if not isinstance(authorization, str) or not authorization:
        raise _unauthorized("nex.authorization_missing", "authorization is required")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token or token != token.strip():
        raise _unauthorized(
            "nex.authorization_invalid", "authorization must use the Bearer scheme"
        )
    return token


def _response_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ServiceTokenAdmissionError(
            503,
            "nex.oa_auth_response_invalid",
            f"OA {label} response is invalid",
            retryable=True,
        ) from exc
    if not isinstance(payload, Mapping):
        raise ServiceTokenAdmissionError(
            503,
            "nex.oa_auth_response_invalid",
            f"OA {label} response is invalid",
            retryable=True,
        )
    return dict(payload)


def _scope_sequence(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError("required scopes must be a sequence")
    scopes = tuple(_nonempty_string(item, "required scope") for item in value)
    if len(scopes) != len(set(scopes)):
        raise ValueError("required scopes must be unique")
    return scopes


def _service_ids(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError("legacy mock callers must be a sequence")
    services = tuple(_nonempty_string(item, "legacy mock caller") for item in value)
    if len(services) != len(set(services)):
        raise ValueError("legacy mock callers must be unique")
    return services


def _route_class(value: object) -> str:
    if not isinstance(value, str) or value not in TOKEN_ROUTE_CLASSES:
        raise ValueError("unsupported service-token route class")
    return value


def _base_url(value: object) -> str:
    url = _nonempty_string(value, "OA base URL")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("OA base URL must use HTTP or HTTPS")
    return url


def _timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("OA auth timeout must be numeric")
    parsed = float(value)
    if parsed <= 0 or parsed > MAX_OA_AUTH_TIMEOUT_SECONDS:
        raise ValueError("OA auth timeout is outside the supported range")
    return parsed


def _timeout_env(env: Mapping[str, str]) -> float:
    raw = env.get(
        "NEX_OA_AUTH_TIMEOUT_SECONDS", str(DEFAULT_OA_AUTH_TIMEOUT_SECONDS)
    )
    try:
        return _timeout(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("NEX_OA_AUTH_TIMEOUT_SECONDS is invalid") from exc


def _optional_integer_env(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not _positive_integer(value):
        raise ValueError(f"{name} must be positive")
    return value


def _secret_token(value: object, field: str) -> str:
    return _nonempty_string(value, field)


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_integer(value: object) -> bool:
    return _nonnegative_integer(value) and value > 0


def _unauthorized(code: str, detail: str) -> ServiceTokenAdmissionError:
    return ServiceTokenAdmissionError(401, code, detail)


def _forbidden(code: str, detail: str) -> ServiceTokenAdmissionError:
    return ServiceTokenAdmissionError(403, code, detail)
