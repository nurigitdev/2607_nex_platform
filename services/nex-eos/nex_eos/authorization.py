from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

EOS_VOUCHER_CREATE_SCOPE = "finance:voucher-draft:create"
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")
_FRESH_AUTHORIZATION_CACHE_CONTROL = "no-store, max-age=0"
_SUBJECT_DENIAL_CODES = frozenset(
    {
        "oa.authorization_membership_inactive",
        "oa.authorization_membership_not_found",
    }
)


class EosAuthorizationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


class AuthorizationSubjectDenied(RuntimeError):
    pass


class AuthorizationSource(Protocol):
    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class EosAuthorizationTarget:
    tenant_id: str
    subject_id: str
    service_subject: str
    service_audience: str
    service_scopes: Sequence[str]
    project_id: str
    resource_type: str
    resource_id: str
    org_unit_id: str | None = None


@dataclass(frozen=True)
class EosAuthorizationEvidence:
    tenant_id: str
    subject_id: str
    service_subject: str
    required_scope: str
    project_id: str
    resource_type: str
    resource_id: str
    org_unit_id: str | None
    authorization_revision_hash: str
    authorization_checked_at: datetime

    def to_metadata(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "service_subject": self.service_subject,
            "required_scope": self.required_scope,
            "project_id": self.project_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "org_unit_id": self.org_unit_id,
            "authorization_revision_hash": self.authorization_revision_hash,
            "authorization_checked_at": self.authorization_checked_at,
        }


class EosVoucherAuthorizationClient:
    def __init__(
        self,
        source: AuthorizationSource,
        *,
        clock=None,
    ) -> None:
        self._source = source
        self._clock = clock or (lambda: datetime.now(UTC))

    def authorize_create(
        self, target: EosAuthorizationTarget
    ) -> EosAuthorizationEvidence:
        normalized = _normalize_target(target)
        try:
            authorization = self._source.effective_authorization(
                tenant_id=normalized.tenant_id,
                subject_id=normalized.subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied() from exc
        except Exception as exc:
            raise EosAuthorizationError(
                "EOS_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable.",
                status_code=503,
                retryable=True,
            ) from exc
        revision_hash = _require_authorization(authorization, normalized)
        checked_at = self._clock()
        if not isinstance(checked_at, datetime) or checked_at.tzinfo is None:
            raise EosAuthorizationError(
                "EOS_AUTHORIZATION_CLOCK_INVALID",
                "Authorization clock must return a timezone-aware datetime.",
                status_code=500,
            )
        return EosAuthorizationEvidence(
            tenant_id=normalized.tenant_id,
            subject_id=normalized.subject_id,
            service_subject=normalized.service_subject,
            required_scope=EOS_VOUCHER_CREATE_SCOPE,
            project_id=normalized.project_id,
            resource_type=normalized.resource_type,
            resource_id=normalized.resource_id,
            org_unit_id=normalized.org_unit_id,
            authorization_revision_hash=revision_hash,
            authorization_checked_at=checked_at.astimezone(UTC),
        )


class HttpOaAuthorizationSource:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]:
        if not self._service_token.strip():
            raise RuntimeError("service token is not configured")
        request = Request(
            f"{self._base_url}/internal/v1/auth/tenants/"
            f"{quote(tenant_id, safe='')}/subjects/{quote(subject_id, safe='')}"
            "/authorization",
            method="GET",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "Cache-Control": _FRESH_AUTHORIZATION_CACHE_CONTROL,
                "Pragma": "no-cache",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if _problem_error_code(exc) in _SUBJECT_DENIAL_CODES:
                raise AuthorizationSubjectDenied(
                    "OA denied the subject authorization request."
                ) from exc
            raise RuntimeError(f"OA authorization failed with HTTP {exc.code}") from exc
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OA authorization request failed") from exc
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("authorization"), Mapping
        ):
            raise AuthorizationSubjectDenied("OA authorization response is malformed.")
        return {**payload["authorization"], "active": True}


def _normalize_target(value: object) -> EosAuthorizationTarget:
    if not isinstance(value, EosAuthorizationTarget):
        raise _invalid("target must be EosAuthorizationTarget")
    service_scopes = _string_set(value.service_scopes, "service_scopes")
    if value.service_audience != "nex-eos" or "service:call" not in service_scopes:
        raise EosAuthorizationError(
            "EOS_SERVICE_TRUST_DENIED",
            "Authenticated service trust for the nex-eos audience is required.",
            status_code=403,
        )
    return EosAuthorizationTarget(
        tenant_id=_scoped_id("tenant_id", value.tenant_id),
        subject_id=_scoped_id("subject_id", value.subject_id),
        service_subject=_scoped_id("service_subject", value.service_subject),
        service_audience="nex-eos",
        service_scopes=tuple(sorted(service_scopes)),
        project_id=_scoped_id("project_id", value.project_id),
        resource_type=_scoped_id("resource_type", value.resource_type),
        resource_id=_scoped_id("resource_id", value.resource_id),
        org_unit_id=(
            _scoped_id("org_unit_id", value.org_unit_id)
            if value.org_unit_id is not None
            else None
        ),
    )


def _require_authorization(
    value: object, target: EosAuthorizationTarget
) -> str:
    if not isinstance(value, Mapping):
        raise _denied()
    if value.get("active") is not True:
        raise _denied()
    if value.get("tenant_id") != target.tenant_id or value.get(
        "subject_id"
    ) != target.subject_id:
        raise _denied()
    scopes = _string_set(value.get("scopes"), "scopes", deny=True)
    if EOS_VOUCHER_CREATE_SCOPE not in scopes:
        raise _denied()
    revision_hash = value.get("revision_hash")
    if not isinstance(revision_hash, str) or not _REVISION_HASH.fullmatch(
        revision_hash
    ):
        raise _denied()
    _require_optional_scope(value, "project_ids", target.project_id)
    if target.org_unit_id is not None:
        _require_optional_scope(value, "org_unit_ids", target.org_unit_id)
    _require_optional_scope(
        value,
        "resource_refs",
        f"{target.resource_type}:{target.resource_id}",
    )
    return revision_hash


def _require_optional_scope(
    authorization: Mapping[str, Any], field_name: str, required: str
) -> None:
    value = authorization.get(field_name)
    if value is None:
        return
    if required not in _string_set(value, field_name, deny=True):
        raise _denied()


def _string_set(value: object, field_name: str, *, deny: bool = False) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        if deny:
            raise _denied()
        raise _invalid(f"{field_name} must be a sequence")
    normalized = {
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip() == item and item
    }
    if len(normalized) != len(value):
        if deny:
            raise _denied()
        raise _invalid(f"{field_name} contains an invalid value")
    return normalized


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field_name} has an invalid format")
    return value


def _problem_error_code(exc: HTTPError) -> str | None:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("error_code")
    return value if isinstance(value, str) else None


def _denied() -> EosAuthorizationError:
    return EosAuthorizationError(
        "EOS_AUTHORIZATION_DENIED",
        "Current finance:voucher-draft:create authorization was denied.",
        status_code=403,
    )


def _invalid(detail: str) -> EosAuthorizationError:
    return EosAuthorizationError(
        "EOS_AUTHORIZATION_REQUEST_INVALID", detail, status_code=422
    )
