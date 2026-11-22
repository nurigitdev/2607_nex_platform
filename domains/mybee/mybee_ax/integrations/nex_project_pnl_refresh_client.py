"""Strict MyBee consumer for EOS allocation-to-P&L activation."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

PROJECT_PNL_REFRESH_OPERATION = "FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION"
PROJECT_PNL_REFRESH_PATH = (
    "/internal/v2/finance/cost-allocation-batches/{batch_id}:refresh-project-pnl"
)
PROJECT_PNL_REFRESH_SCHEMA = "eos_project_pnl_refresh_from_allocation.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_RESPONSE_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "tenant_id",
        "company_id",
        "batch_id",
        "period_id",
        "allocation_reconciliation_hash",
        "disposition",
        "projections",
        "refresh_hash",
    }
)
_PROJECTION_FIELDS = frozenset(
    {
        "project_id",
        "project_code",
        "projection_id",
        "projection_version",
        "projection_hash",
        "reconciliation_status",
        "freshness_status",
    }
)


class ProjectPnlRefreshConsumerError(RuntimeError):
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


@dataclass(frozen=True)
class ProjectPnlRefreshProviderRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    company_id: str
    batch_id: str
    correlation_id: str


class ProjectPnlRefreshProviderTransport(Protocol):
    def send(self, request: ProjectPnlRefreshProviderRequest) -> Mapping[str, Any]: ...


class NexProjectPnlRefreshClient:
    def __init__(self, transport: ProjectPnlRefreshProviderTransport) -> None:
        self._transport = transport

    def refresh(
        self,
        *,
        tenant_id: str,
        company_id: str,
        batch_id: str,
        correlation_id: str,
    ) -> Mapping[str, Any]:
        request = build_project_pnl_refresh_request(
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch_id,
            correlation_id=correlation_id,
        )
        return self.refresh_request(request)

    def refresh_request(
        self, request: ProjectPnlRefreshProviderRequest
    ) -> Mapping[str, Any]:
        return admit_project_pnl_refresh_result(
            self._transport.send(request), request=request
        )


class HttpProjectPnlRefreshProviderTransport:
    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid("MYBEE_PNL_REFRESH_BASE_URL_INVALID", "http(s) URL required")
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid(
                "MYBEE_PNL_REFRESH_SERVICE_TOKEN_MISSING",
                "service token is required",
            )
        if timeout_seconds <= 0:
            raise _invalid(
                "MYBEE_PNL_REFRESH_TIMEOUT_INVALID", "positive timeout required"
            )
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: ProjectPnlRefreshProviderRequest) -> Mapping[str, Any]:
        outgoing = Request(
            urljoin(self._base_url, request.path.lstrip("/")),
            method=request.method,
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "X-NeX-Tenant-Id": request.tenant_id,
                "X-NeX-Company-Id": request.company_id,
                "X-NeX-Correlation-Id": request.correlation_id,
            },
        )
        try:
            with urlopen(outgoing, timeout=self._timeout_seconds) as response:
                return _json_object(response.read())
        except HTTPError as exc:
            problem = _optional_json_object(exc.read())
            raise ProjectPnlRefreshConsumerError(
                str(problem.get("error_code", "EOS_PROJECT_PNL_REFRESH_REJECTED")),
                "EOS rejected allocation-to-P&L refresh",
                status_code=exc.code,
                retryable=bool(problem.get("retryable", exc.code >= 500)),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProjectPnlRefreshConsumerError(
                "EOS_PROJECT_PNL_REFRESH_UNAVAILABLE",
                "EOS allocation-to-P&L refresh is unavailable",
                status_code=503,
                retryable=True,
            ) from exc


def build_project_pnl_refresh_request(
    *,
    tenant_id: str,
    company_id: str,
    batch_id: str,
    correlation_id: str,
) -> ProjectPnlRefreshProviderRequest:
    tenant = _scoped_id("tenant_id", tenant_id)
    company = _request_uuid("company_id", company_id)
    batch = _request_uuid("batch_id", batch_id)
    correlation = _scoped_id("correlation_id", correlation_id)
    return ProjectPnlRefreshProviderRequest(
        method="POST",
        path=PROJECT_PNL_REFRESH_PATH.format(batch_id=batch),
        operation_id=PROJECT_PNL_REFRESH_OPERATION,
        tenant_id=tenant,
        company_id=company,
        batch_id=batch,
        correlation_id=correlation,
    )


def admit_project_pnl_refresh_result(
    value: object, *, request: ProjectPnlRefreshProviderRequest
) -> Mapping[str, Any]:
    result = _exact_object("result", value, _RESPONSE_FIELDS)
    if (
        result["schema_version"] != PROJECT_PNL_REFRESH_SCHEMA
        or result["operation"] != PROJECT_PNL_REFRESH_OPERATION
        or result["tenant_id"] != request.tenant_id
        or result["company_id"] != request.company_id
        or result["batch_id"] != request.batch_id
    ):
        raise _drift("Project P&L refresh identity or schema drifted")
    _response_uuid("period_id", result["period_id"])
    _hash_ref("allocation_reconciliation_hash", result["allocation_reconciliation_hash"])
    if result["disposition"] not in {"CREATED", "EXACT_REPLAY"}:
        raise _drift("Project P&L refresh disposition drifted")

    raw_projections = result["projections"]
    if not isinstance(raw_projections, list) or not raw_projections:
        raise _drift("Project P&L refresh projections must be a non-empty array")
    projections: list[Mapping[str, Any]] = []
    project_ids: set[str] = set()
    projection_ids: set[str] = set()
    for item in raw_projections:
        projection = _exact_object("projection", item, _PROJECTION_FIELDS)
        project_id = _response_uuid("project_id", projection["project_id"])
        projection_id = _response_uuid("projection_id", projection["projection_id"])
        if project_id in project_ids or projection_id in projection_ids:
            raise _drift("Project P&L refresh projection identity is duplicated")
        project_ids.add(project_id)
        projection_ids.add(projection_id)
        if not _PROJECT_CODE.fullmatch(str(projection["project_code"])):
            raise _drift("Project P&L refresh project_code drifted")
        _positive_int("projection_version", projection["projection_version"])
        _hash_ref("projection_hash", projection["projection_hash"])
        if (
            projection["reconciliation_status"] != "VERIFIED"
            or projection["freshness_status"] != "CURRENT"
        ):
            raise _drift("Project P&L refresh projection is not ready")
        projections.append(MappingProxyType(projection))
    if [item["project_id"] for item in projections] != sorted(project_ids):
        raise _drift("Project P&L refresh projections are not deterministically ordered")

    semantics = {
        "schema_version": result["schema_version"],
        "operation": result["operation"],
        "tenant_id": result["tenant_id"],
        "company_id": result["company_id"],
        "batch_id": result["batch_id"],
        "period_id": result["period_id"],
        "allocation_reconciliation_hash": result["allocation_reconciliation_hash"],
        "projections": [dict(item) for item in projections],
    }
    refresh_hash = _hash_ref("refresh_hash", result["refresh_hash"])
    expected_hash = semantic_sha256_hash_ref(
        {"domain": "EOS-PROJECT-PNL-REFRESH-V1", **semantics}
    )
    if refresh_hash != expected_hash:
        raise _drift("Project P&L refresh semantic hash drifted")
    return MappingProxyType({**result, "projections": tuple(projections)})


def _exact_object(name: str, value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _drift(f"{name} fields drifted")
    return dict(value)


def _json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _drift("EOS Project P&L refresh response is not JSON") from exc
    if not isinstance(value, Mapping):
        raise _drift("EOS Project P&L refresh response is not an object")
    return value


def _optional_json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _scoped_id(name: str, value: object) -> str:
    text = str(value).strip()
    if not _SCOPED_ID.fullmatch(text):
        raise _invalid("MYBEE_PNL_REFRESH_ARGUMENT_INVALID", f"{name} is invalid")
    return text


def _request_uuid(name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(
            "MYBEE_PNL_REFRESH_ARGUMENT_INVALID", f"{name} must be a UUID"
        ) from exc


def _response_uuid(name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _drift(f"{name} must be a UUID") from exc


def _hash_ref(name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _drift(f"{name} must be a sha256 hash reference") from exc


def _positive_int(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise _drift(f"{name} must be positive")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _drift(f"{name} must be positive") from exc
    if parsed <= 0 or parsed != value:
        raise _drift(f"{name} must be positive")
    return parsed


def _invalid(error_code: str, detail: str) -> ProjectPnlRefreshConsumerError:
    return ProjectPnlRefreshConsumerError(error_code, detail, status_code=400)


def _drift(detail: str) -> ProjectPnlRefreshConsumerError:
    return ProjectPnlRefreshConsumerError(
        "MYBEE_PNL_REFRESH_CONTRACT_DRIFT", detail, status_code=502
    )
