from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
from nex_runtime import SERVICE_SPECS
from nex_runtime.semantic_hashes import validate_hash_ref

from .service_auth import AeOutboundServiceTokenError, resolve_ae_outbound_service_token

EOS_COA_RESOLVE_PATH = "/internal/v2/finance/accounts/resolve-semantic"
DEFAULT_EOS_BASE_URL = f"http://127.0.0.1:{SERVICE_SPECS['nex-eos'].default_port}"
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SEMANTIC_KEY = re.compile(r"^MB-COA-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

HttpRequester = Callable[..., httpx.Response]


@dataclass(frozen=True)
class CoaSemanticResolutionError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpEosSemanticAccountResolver:
    base_url: str = DEFAULT_EOS_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 10.0
    requester: HttpRequester = httpx.request

    def __post_init__(self) -> None:
        _base_url(self.base_url)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("EOS semantic resolver timeout must be positive")

    def resolve(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        company_id: str,
        semantic_key: str,
        effective_on: date,
        currency: str,
    ) -> dict[str, Any]:
        params = {
            "company_id": _uuid("company_id", company_id),
            "semantic_key": _semantic_key(semantic_key),
            "effective_on": _date("effective_on", effective_on).isoformat(),
            "currency": _currency(currency),
        }
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token, audience="nex-eos"
            )
        except AeOutboundServiceTokenError as exc:
            raise CoaSemanticResolutionError(
                "ae.coa_semantic.service_token_unavailable",
                "EOS service authentication is unavailable.",
            ) from exc
        try:
            response = self.requester(
                "GET",
                f"{self.base_url.rstrip('/')}{EOS_COA_RESOLVE_PATH}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-NeX-Tenant-Id": tenant_id,
                    "X-NeX-Subject-Id": requester_subject_id,
                    "X-Service-ID": "nex-ae-api",
                },
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise CoaSemanticResolutionError(
                "ae.coa_semantic.timeout",
                "EOS semantic Account resolution timed out.",
                True,
            ) from exc
        except httpx.HTTPError as exc:
            raise CoaSemanticResolutionError(
                "ae.coa_semantic.transport_failed",
                "EOS semantic Account resolution transport failed.",
                True,
            ) from exc
        payload = _response_object(response)
        if response.status_code != 200:
            retryable = response.status_code >= 500
            raise CoaSemanticResolutionError(
                str(payload.get("error_code") or "ae.coa_semantic.rejected"),
                "EOS rejected semantic Account resolution.",
                retryable,
                response.status_code,
            )
        return _resolution(payload, expected={"tenant_id": tenant_id, **params})


def build_nsl_semantic_account_result(
    resolver: HttpEosSemanticAccountResolver,
    *,
    tenant_id: str,
    requester_subject_id: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.arguments_invalid",
            "NSL semantic Account arguments must be an object.",
        )
    return resolver.resolve(
        tenant_id=tenant_id,
        requester_subject_id=requester_subject_id,
        company_id=arguments.get("company_id"),
        semantic_key=arguments.get("semantic_key"),
        effective_on=_date_input("effective_on", arguments.get("effective_on")),
        currency=arguments.get("currency"),
    )


def _resolution(
    value: object, *, expected: Mapping[str, str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid_response()
    required = {
        "schema_version",
        "tenant_id",
        "company_id",
        "effective_on",
        "currency",
        "semantic_key",
        "account_ref",
        "account_code",
        "account_name",
        "category",
        "account_type",
        "statement_line_ref",
        "definition_account_code",
        "evidence",
        "evidence_hash",
    }
    if set(value) != required or value.get("schema_version") != (
        "eos_coa_semantic_account_resolution.v1"
    ):
        raise _invalid_response()
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise _invalid_response()
    account_ref = value.get("account_ref")
    if (
        not isinstance(account_ref, Mapping)
        or set(account_ref) != {"type", "id"}
        or account_ref.get("type") != "eos.account"
    ):
        raise _invalid_response()
    try:
        _uuid("account_ref.id", account_ref.get("id"))
    except CoaSemanticResolutionError as exc:
        raise _invalid_response() from exc
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping) or not evidence:
        raise _invalid_response()
    try:
        validate_hash_ref(value.get("evidence_hash"))
    except (TypeError, ValueError) as exc:
        raise _invalid_response() from exc
    return dict(value)


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.response_invalid",
            "EOS semantic Account response is invalid.",
            response.status_code >= 500,
            response.status_code,
        ) from exc
    if not isinstance(value, dict):
        raise _invalid_response()
    return value


def _base_url(value: object) -> str:
    parsed = httpx.URL(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError("EOS semantic resolver base URL is invalid")
    return str(value).rstrip("/")


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.request_invalid", f"{field} is invalid."
        )
    return normalized


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.request_invalid", f"{field} is invalid."
        ) from exc


def _semantic_key(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _SEMANTIC_KEY.fullmatch(normalized) is None:
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.request_invalid", "semantic_key is invalid."
        )
    return normalized


def _currency(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _CURRENCY.fullmatch(normalized) is None:
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.request_invalid", "currency is invalid."
        )
    return normalized


def _date(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.request_invalid", f"{field} is invalid."
        )
    return value


def _date_input(field: str, value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CoaSemanticResolutionError(
            "ae.coa_semantic.arguments_invalid", f"{field} is invalid."
        ) from exc


def _invalid_response() -> CoaSemanticResolutionError:
    return CoaSemanticResolutionError(
        "ae.coa_semantic.response_invalid",
        "EOS semantic Account response is invalid.",
    )
