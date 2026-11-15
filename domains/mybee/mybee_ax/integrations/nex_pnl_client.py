"""Strict MyBee consumer for the authorized EOS Project P&L read model."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

PROJECT_PNL_GET_OPERATION = "FINANCE.PROJECT_PNL.GET"
PROJECT_PNL_GET_PATH = "/internal/v2/finance/projects/{project_id}/pnl/{period_id}"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_AMOUNT = re.compile(r"^-?[0-9]+\.[0-9]{4}$")

_HEADER_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "company_id",
        "projection_id",
        "project_id",
        "project_code",
        "period_id",
        "projection_version",
        "functional_currency",
        "as_of",
        "posting_watermark",
        "posting_watermark_at",
        "allocation_watermark",
        "allocation_watermark_at",
        "budget_watermark",
        "budget_watermark_at",
        "payroll_evidence_watermark",
        "payroll_evidence_watermark_at",
        "labor_effort_watermark",
        "labor_effort_watermark_at",
        "material_commitment_watermark",
        "material_commitment_watermark_at",
        "reconciliation_status",
        "freshness_status",
        "staleness_seconds",
        "posted_revenue",
        "posted_direct_cost",
        "posted_allocated_cost",
        "posted_operating_result",
        "operating_unallocated_cost",
        "planned_budget",
        "budget_actual",
        "budget_variance",
        "approved_not_posted",
        "forecast",
        "data_classification",
        "projection_hash",
        "components",
    }
)
_COMPONENT_FIELDS = frozenset(
    {
        "line_no",
        "classification",
        "rollup_class",
        "source_kind",
        "account_id",
        "work_code",
        "functional_amount",
        "confirmed",
        "source_ref",
        "source_hash",
        "data_classification",
        "component_hash",
    }
)
_CLASSIFICATION = {
    "POSTED_REVENUE": ("REVENUE", True),
    "POSTED_DIRECT_COST": ("DIRECT_COST", True),
    "POSTED_ALLOCATED_COST": ("ALLOCATED_COST", True),
    "POSTED_LABOR_ALLOCATED": ("ALLOCATED_COST", True),
    "UNALLOCATED": ("UNALLOCATED_COST", False),
    "POSTED_PAYROLL_UNALLOCATED": ("UNALLOCATED_COST", False),
    "UNALLOCATED_LABOR_OVERHEAD": ("UNALLOCATED_COST", False),
    "APPROVED_NOT_POSTED": ("NONFINAL", False),
    "LABOR_ALLOCATION_PROVISIONAL": ("PROVISIONAL", False),
    "PLANNED_BUDGET": ("BUDGET", False),
    "FORECAST": ("FORECAST", False),
    "PLANNED_LABOR": ("FORECAST", False),
    "BOM_FORECAST": ("FORECAST", False),
    "MATERIAL_COMMITTED": ("COMMITMENT", False),
    "UNASSIGNED_INVENTORY": ("COMMITMENT", False),
    "LABOR_ADJUSTMENT": ("ALLOCATED_COST", True),
    "MATERIAL_VARIANCE": ("ADJUSTMENT", True),
    "FX_REALIZED_GAIN_LOSS": ("ADJUSTMENT", True),
    "FX_UNREALIZED_GAIN_LOSS": ("ADJUSTMENT", True),
}
_SOURCE_KINDS = frozenset(
    {
        "REVENUE",
        "PAYROLL",
        "MATERIAL",
        "SERVICE",
        "SHARED_EXPENSE",
        "FX_GAIN_LOSS",
        "OTHER",
    }
)
_DATA_CLASSES = frozenset(
    {"INTERNAL_FINANCIAL", "CONFIDENTIAL_FINANCIAL", "PAYROLL_SENSITIVE"}
)
_RECONCILIATION = frozenset({"VERIFIED", "PENDING", "BLOCKED", "PARTIAL"})
_FRESHNESS = frozenset({"CURRENT", "STALE", "UNKNOWN"})


class ProjectPnlConsumerError(RuntimeError):
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
class ProjectPnlProviderRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    company_id: str
    subject_id: str
    correlation_id: str


class ProjectPnlProviderTransport(Protocol):
    def send(self, request: ProjectPnlProviderRequest) -> Mapping[str, Any]: ...


class NexProjectPnlClient:
    def __init__(self, transport: ProjectPnlProviderTransport) -> None:
        self._transport = transport

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        project_code: str,
        period_id: str,
        subject_id: str,
        correlation_id: str,
        projection_version: int | None = None,
    ) -> Mapping[str, Any]:
        request = build_project_pnl_request(
            tenant_id=tenant_id,
            company_id=company_id,
            project_id=project_id,
            period_id=period_id,
            subject_id=subject_id,
            correlation_id=correlation_id,
            projection_version=projection_version,
        )
        return admit_project_pnl_projection(
            self._transport.send(request),
            tenant_id=request.tenant_id,
            company_id=request.company_id,
            project_id=project_id,
            project_code=project_code,
            period_id=period_id,
            projection_version=projection_version,
        )


class HttpProjectPnlProviderTransport:
    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid("MYBEE_PNL_BASE_URL_INVALID", "http(s) URL required")
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid(
                "MYBEE_PNL_SERVICE_TOKEN_MISSING", "service token is required"
            )
        if timeout_seconds <= 0:
            raise _invalid("MYBEE_PNL_TIMEOUT_INVALID", "positive timeout required")
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: ProjectPnlProviderRequest) -> Mapping[str, Any]:
        outgoing = Request(
            urljoin(self._base_url, request.path.lstrip("/")),
            method=request.method,
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "X-NeX-Tenant-Id": request.tenant_id,
                "X-NeX-Company-Id": request.company_id,
                "X-NeX-Subject-Id": request.subject_id,
                "X-NeX-Correlation-Id": request.correlation_id,
            },
        )
        try:
            with urlopen(outgoing, timeout=self._timeout_seconds) as response:
                return _json_object(response.read())
        except HTTPError as exc:
            problem = _optional_json_object(exc.read())
            raise ProjectPnlConsumerError(
                str(problem.get("error_code", "EOS_PROJECT_PNL_REJECTED")),
                "EOS rejected the Project P&L query",
                status_code=exc.code,
                retryable=bool(problem.get("retryable", exc.code >= 500)),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProjectPnlConsumerError(
                "EOS_PROJECT_PNL_UNAVAILABLE",
                "EOS Project P&L endpoint is unavailable",
                status_code=503,
                retryable=True,
            ) from exc


def build_project_pnl_request(
    *,
    tenant_id: str,
    company_id: str,
    project_id: str,
    period_id: str,
    subject_id: str,
    correlation_id: str,
    projection_version: int | None = None,
) -> ProjectPnlProviderRequest:
    tenant_id = _scoped_id("tenant_id", tenant_id, 128)
    company_id = _uuid("company_id", company_id)
    project_id = _uuid("project_id", project_id)
    period_id = _uuid("period_id", period_id)
    subject_id = _scoped_id("subject_id", subject_id, 128)
    correlation_id = _scoped_id("correlation_id", correlation_id, 128)
    path = PROJECT_PNL_GET_PATH.format(project_id=project_id, period_id=period_id)
    if projection_version is not None:
        path = f"{path}?{urlencode({'projection_version': _positive_int('projection_version', projection_version)})}"
    return ProjectPnlProviderRequest(
        method="GET",
        path=path,
        operation_id=PROJECT_PNL_GET_OPERATION,
        tenant_id=tenant_id,
        company_id=company_id,
        subject_id=subject_id,
        correlation_id=correlation_id,
    )


def admit_project_pnl_projection(
    value: object,
    *,
    tenant_id: str,
    company_id: str,
    project_id: str,
    project_code: str,
    period_id: str,
    projection_version: int | None = None,
) -> Mapping[str, Any]:
    projection = _exact_object("projection", value, _HEADER_FIELDS)
    expected = {
        "tenant_id": _scoped_id("tenant_id", tenant_id, 128),
        "company_id": _uuid("company_id", company_id),
        "project_id": _uuid("project_id", project_id),
        "project_code": _project_code(project_code),
        "period_id": _uuid("period_id", period_id),
    }
    if projection.get("schema_version") != "eos_project_pnl_projection.v1" or any(
        projection.get(name) != expected_value
        for name, expected_value in expected.items()
    ):
        raise _drift("Project P&L query identity or schema drifted")
    version = _response_positive_int(
        "projection_version", projection["projection_version"]
    )
    if projection_version is not None and version != _positive_int(
        "expected_projection_version", projection_version
    ):
        raise _drift("Project P&L projection version drifted")
    _response_uuid("projection_id", projection["projection_id"])
    _pattern("functional_currency", projection["functional_currency"], _CURRENCY)
    as_of = _timestamp("as_of", projection["as_of"])
    watermark_times = [
        _required_watermark(projection, "posting_watermark"),
        _required_watermark(projection, "allocation_watermark"),
    ]
    for name in (
        "budget_watermark",
        "payroll_evidence_watermark",
        "labor_effort_watermark",
        "material_commitment_watermark",
    ):
        observed_at = _optional_watermark(projection, name)
        if observed_at is not None:
            watermark_times.append(observed_at)
    if any(item > as_of for item in watermark_times):
        raise _drift("Project P&L watermark is later than as_of")
    _choice(
        "reconciliation_status", projection["reconciliation_status"], _RECONCILIATION
    )
    _choice("freshness_status", projection["freshness_status"], _FRESHNESS)
    _nonnegative_int("staleness_seconds", projection["staleness_seconds"])
    _choice("data_classification", projection["data_classification"], _DATA_CLASSES)
    _hash_ref("projection_hash", projection["projection_hash"])

    components = projection["components"]
    if not isinstance(components, list):
        raise _drift("Project P&L components must be an array")
    rollups: dict[str, Decimal] = {}
    component_hashes: set[str] = set()
    admitted_components: list[Mapping[str, Any]] = []
    for expected_line, item in enumerate(components, 1):
        component = _admit_component(item, expected_line=expected_line)
        component_hash = str(component["component_hash"])
        if component_hash in component_hashes:
            raise _drift("Project P&L component hash is duplicated")
        component_hashes.add(component_hash)
        rollup = str(component["rollup_class"])
        rollups[rollup] = rollups.get(rollup, Decimal("0.0000")) + Decimal(
            str(component["functional_amount"])
        )
        admitted_components.append(component)

    amounts = {
        name: _amount(name, projection[name])
        for name in (
            "posted_revenue",
            "posted_direct_cost",
            "posted_allocated_cost",
            "posted_operating_result",
            "operating_unallocated_cost",
            "planned_budget",
            "budget_actual",
            "budget_variance",
            "approved_not_posted",
            "forecast",
        )
    }
    expected_amounts = {
        "posted_revenue": rollups.get("REVENUE", Decimal("0.0000")),
        "posted_direct_cost": rollups.get("DIRECT_COST", Decimal("0.0000")),
        "posted_allocated_cost": rollups.get("ALLOCATED_COST", Decimal("0.0000")),
        "operating_unallocated_cost": rollups.get(
            "UNALLOCATED_COST", Decimal("0.0000")
        ),
        "planned_budget": rollups.get("BUDGET", Decimal("0.0000")),
        "approved_not_posted": rollups.get("NONFINAL", Decimal("0.0000")),
        "forecast": rollups.get("FORECAST", Decimal("0.0000")),
    }
    if any(amounts[name] != amount for name, amount in expected_amounts.items()):
        raise _drift("Project P&L header totals differ from components")
    if (
        amounts["posted_operating_result"]
        != amounts["posted_revenue"]
        - amounts["posted_direct_cost"]
        - amounts["posted_allocated_cost"]
        or amounts["budget_actual"]
        != amounts["posted_direct_cost"] + amounts["posted_allocated_cost"]
        or amounts["budget_variance"]
        != amounts["planned_budget"] - amounts["budget_actual"]
    ):
        raise _drift("Project P&L rollup arithmetic drifted")
    return MappingProxyType({**projection, "components": tuple(admitted_components)})


def _admit_component(value: object, *, expected_line: int) -> Mapping[str, Any]:
    component = _exact_object("component", value, _COMPONENT_FIELDS)
    if _response_positive_int("line_no", component["line_no"]) != expected_line:
        raise _drift("Project P&L component ordering drifted")
    classification = _choice(
        "classification", component["classification"], frozenset(_CLASSIFICATION)
    )
    expected_rollup, expected_confirmed = _CLASSIFICATION[classification]
    if (
        component["rollup_class"] != expected_rollup
        or component["confirmed"] is not expected_confirmed
    ):
        raise _drift("Project P&L classification semantics drifted")
    _choice("source_kind", component["source_kind"], _SOURCE_KINDS)
    if component["account_id"] is not None:
        _response_uuid("account_id", component["account_id"])
    if component["work_code"] is not None:
        _text("work_code", component["work_code"], 32)
    if _amount("functional_amount", component["functional_amount"]) == 0:
        raise _drift("Project P&L component amount must not be zero")
    _text("source_ref", component["source_ref"], 256)
    _hash_ref("source_hash", component["source_hash"])
    _choice("data_classification", component["data_classification"], _DATA_CLASSES)
    _hash_ref("component_hash", component["component_hash"])
    return MappingProxyType(component)


def _required_watermark(value: Mapping[str, Any], name: str) -> datetime:
    _text(name, value[name], 256)
    return _timestamp(f"{name}_at", value[f"{name}_at"])


def _optional_watermark(value: Mapping[str, Any], name: str) -> datetime | None:
    reference = value[name]
    observed_at = value[f"{name}_at"]
    if reference is None and observed_at is None:
        return None
    if reference is None or observed_at is None:
        raise _drift(f"{name} reference and timestamp must be paired")
    _text(name, reference, 256)
    return _timestamp(f"{name}_at", observed_at)


def _exact_object(name: str, value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _drift(f"{name} fields drifted")
    return dict(value)


def _json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _drift("EOS Project P&L response is not JSON") from exc
    if not isinstance(value, Mapping):
        raise _drift("EOS Project P&L response is not an object")
    return value


def _optional_json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _scoped_id(name: str, value: Any, limit: int) -> str:
    text = str(value).strip()
    if len(text) > limit or not _SCOPED_ID.fullmatch(text):
        raise _invalid("MYBEE_PNL_ARGUMENT_INVALID", f"{name} is invalid")
    return text


def _uuid(name: str, value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid("MYBEE_PNL_ARGUMENT_INVALID", f"{name} must be a UUID") from exc


def _response_uuid(name: str, value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _drift(f"{name} must be a UUID") from exc


def _project_code(value: Any) -> str:
    text = str(value).strip().upper()
    if not _PROJECT_CODE.fullmatch(text):
        raise _invalid("MYBEE_PNL_ARGUMENT_INVALID", "project_code is invalid")
    return text


def _text(name: str, value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise _drift(f"{name} is invalid")
    text = value.strip()
    if not text or len(text) > limit:
        raise _drift(f"{name} is invalid")
    return text


def _pattern(name: str, value: Any, pattern: re.Pattern[str]) -> str:
    text = str(value).strip()
    if not pattern.fullmatch(text):
        raise _drift(f"{name} is invalid")
    return text


def _hash_ref(name: str, value: Any) -> str:
    return _pattern(name, value, _HASH_REF)


def _choice(name: str, value: Any, choices: frozenset[str]) -> str:
    text = str(value).strip()
    if text not in choices:
        raise _drift(f"{name} is invalid")
    return text


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid("MYBEE_PNL_ARGUMENT_INVALID", f"{name} must be positive")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(
            "MYBEE_PNL_ARGUMENT_INVALID", f"{name} must be positive"
        ) from exc
    if parsed <= 0:
        raise _invalid("MYBEE_PNL_ARGUMENT_INVALID", f"{name} must be positive")
    return parsed


def _response_positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _drift(f"{name} must be positive")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _drift(f"{name} must be positive") from exc
    if parsed <= 0:
        raise _drift(f"{name} must be positive")
    return parsed


def _nonnegative_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _drift(f"{name} must be non-negative")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _drift(f"{name} must be non-negative") from exc
    if parsed < 0:
        raise _drift(f"{name} must be non-negative")
    return parsed


def _amount(name: str, value: Any) -> Decimal:
    text = str(value)
    if not _AMOUNT.fullmatch(text):
        raise _drift(f"{name} must use four-decimal wire format")
    return Decimal(text)


def _timestamp(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise _drift(f"{name} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _drift(f"{name} must be a timestamp") from exc
    if parsed.tzinfo is None:
        raise _drift(f"{name} must include timezone")
    return parsed


def _invalid(error_code: str, detail: str) -> ProjectPnlConsumerError:
    return ProjectPnlConsumerError(error_code, detail, status_code=400)


def _drift(detail: str) -> ProjectPnlConsumerError:
    return ProjectPnlConsumerError("MYBEE_PNL_CONTRACT_DRIFT", detail, status_code=502)
