"""Strict MyBee consumer for EOS approved allocation-plan resolution."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

ALLOCATION_PLAN_RESOLVE_OPERATION = "FINANCE.COST_ALLOCATION_PLAN.RESOLVE"
ALLOCATION_PLAN_RESOLVE_PATH = "/internal/v2/finance/cost-allocation-plans:resolve"
ALLOCATION_PLAN_RESOLVE_SCHEMA = "eos_cost_allocation_plan_resolve.v1"
ALLOCATION_PLAN_RESOLUTION_SCHEMA = "eos_cost_allocation_plan_resolution.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_RATIO = re.compile(r"^(?:0\.(?!0{12}$)[0-9]{12}|1\.000000000000)$")
_BASIS_UNITS = re.compile(r"^[0-9]+\.[0-9]{8}$")
_APPROVAL_PROOF = re.compile(r"^eos\.approval-proof:[0-9a-f-]{36}$")
_SOURCE_KINDS = frozenset(
    {
        "PAYROLL",
        "PURCHASE",
        "SERVICE",
        "SHARED_EXPENSE",
        "REVENUE",
        "FX_GAIN_LOSS",
        "OTHER",
    }
)
_BASIS_KINDS = frozenset(
    {
        "ACTUAL_WORK",
        "APPROVED_PLAN",
        "USAGE",
        "HEADCOUNT_CASCADE",
        "JUSTIFIED_PERCENTAGE",
    }
)
_BASIS_PRIORITY = {
    "ACTUAL_WORK": 1,
    "USAGE": 1,
    "APPROVED_PLAN": 2,
    "HEADCOUNT_CASCADE": 3,
    "JUSTIFIED_PERCENTAGE": 4,
}
_CONFIDENTIALITY = frozenset({"INTERNAL", "CONFIDENTIAL", "RESTRICTED"})
_RESPONSE_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "resolution_disposition",
        "selector_hash",
        "resolution_hash",
        "tenant_id",
        "company_id",
        "plan_id",
        "plan_revision",
        "source_kind",
        "scope_type",
        "basis_kind",
        "basis_priority",
        "rule_release_hash",
        "basis_source_ref",
        "basis_source_hash",
        "effective_start",
        "effective_end",
        "approved_by",
        "approved_proof",
        "state",
        "plan_hash",
        "created_at",
        "lines",
    }
)
_LINE_FIELDS = frozenset(
    {
        "line_no",
        "project_id",
        "project_code",
        "work_code",
        "basis_units",
        "allocation_ratio",
        "eligibility_hash",
        "confidentiality_class",
        "line_hash",
    }
)


class AllocationPlanConsumerError(RuntimeError):
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
class AllocationPlanProviderRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    company_id: str
    correlation_id: str
    body: Mapping[str, Any]


class AllocationPlanProviderTransport(Protocol):
    def send(self, request: AllocationPlanProviderRequest) -> Mapping[str, Any]: ...


class NexAllocationPlanResolverClient:
    def __init__(self, transport: AllocationPlanProviderTransport) -> None:
        self._transport = transport

    def resolve(
        self,
        *,
        tenant_id: str,
        company_id: str,
        source_kind: str,
        effective_on: str,
        projects: Sequence[Mapping[str, Any]],
        correlation_id: str,
    ) -> Mapping[str, Any]:
        request = build_allocation_plan_resolve_request(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=source_kind,
            effective_on=effective_on,
            projects=projects,
            correlation_id=correlation_id,
        )
        return self.resolve_request(request)

    def resolve_request(
        self, request: AllocationPlanProviderRequest
    ) -> Mapping[str, Any]:
        return admit_allocation_plan_resolution(
            self._transport.send(request), request=request
        )


class HttpAllocationPlanProviderTransport:
    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid(
                "MYBEE_ALLOCATION_PLAN_BASE_URL_INVALID", "http(s) URL required"
            )
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid(
                "MYBEE_ALLOCATION_PLAN_SERVICE_TOKEN_MISSING",
                "service token is required",
            )
        if timeout_seconds <= 0:
            raise _invalid(
                "MYBEE_ALLOCATION_PLAN_TIMEOUT_INVALID", "positive timeout required"
            )
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: AllocationPlanProviderRequest) -> Mapping[str, Any]:
        outgoing = Request(
            urljoin(self._base_url, request.path.lstrip("/")),
            data=json.dumps(request.body, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            method=request.method,
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
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
            raise AllocationPlanConsumerError(
                str(problem.get("error_code", "EOS_COST_ALLOCATION_PLAN_REJECTED")),
                "EOS rejected allocation-plan resolution",
                status_code=exc.code,
                retryable=bool(problem.get("retryable", exc.code >= 500)),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AllocationPlanConsumerError(
                "EOS_COST_ALLOCATION_PLAN_UNAVAILABLE",
                "EOS allocation-plan resolver is unavailable",
                status_code=503,
                retryable=True,
            ) from exc


def build_allocation_plan_resolve_request(
    *,
    tenant_id: str,
    company_id: str,
    source_kind: str,
    effective_on: str,
    projects: Sequence[Mapping[str, Any]],
    correlation_id: str,
) -> AllocationPlanProviderRequest:
    tenant = _scoped_id("tenant_id", tenant_id)
    company = _request_uuid("company_id", company_id)
    source = _request_choice("source_kind", source_kind, _SOURCE_KINDS)
    effective = _request_date("effective_on", effective_on)
    correlation = _scoped_id("correlation_id", correlation_id)
    admitted = _projects(projects)
    body = {
        "schema_version": ALLOCATION_PLAN_RESOLVE_SCHEMA,
        "source_kind": source,
        "scope_type": "PROJECT_SET",
        "effective_on": effective,
        "projects": admitted,
    }
    return AllocationPlanProviderRequest(
        method="POST",
        path=ALLOCATION_PLAN_RESOLVE_PATH,
        operation_id=ALLOCATION_PLAN_RESOLVE_OPERATION,
        tenant_id=tenant,
        company_id=company,
        correlation_id=correlation,
        body=body,
    )


def admit_allocation_plan_resolution(
    value: object, *, request: AllocationPlanProviderRequest
) -> Mapping[str, Any]:
    response = _exact_mapping("resolution", value, _RESPONSE_FIELDS)
    if (
        response.get("schema_version") != ALLOCATION_PLAN_RESOLUTION_SCHEMA
        or response.get("operation") != ALLOCATION_PLAN_RESOLVE_OPERATION
        or response.get("resolution_disposition") != "EXACT_MATCH"
        or response.get("tenant_id") != request.tenant_id
        or response.get("company_id") != request.company_id
        or response.get("source_kind") != request.body["source_kind"]
        or response.get("scope_type") != "PROJECT_SET"
        or response.get("state") != "APPROVED"
    ):
        raise _drift("Allocation-plan resolution identity or state drifted")
    _uuid("plan_id", response["plan_id"])
    _positive_int("plan_revision", response["plan_revision"])
    basis_kind = _choice("basis_kind", response["basis_kind"], _BASIS_KINDS)
    if response.get("basis_priority") != _BASIS_PRIORITY[basis_kind]:
        raise _drift("Allocation-plan basis priority drifted")
    for name in (
        "rule_release_hash",
        "basis_source_hash",
        "plan_hash",
        "selector_hash",
        "resolution_hash",
    ):
        _hash(name, response[name])
    _text("basis_source_ref", response["basis_source_ref"], 256)
    _text("approved_by", response["approved_by"], 128)
    if (
        not isinstance(response["approved_proof"], str)
        or _APPROVAL_PROOF.fullmatch(response["approved_proof"]) is None
    ):
        raise _drift("Allocation-plan approval proof is invalid")
    effective_start = _date("effective_start", response["effective_start"])
    effective_end = response["effective_end"]
    if effective_end is not None:
        effective_end = _date("effective_end", effective_end)
    if not (
        effective_start <= request.body["effective_on"]
        and (effective_end is None or effective_end >= request.body["effective_on"])
    ):
        raise _drift("Allocation-plan effective interval drifted")
    _timestamp("created_at", response["created_at"])

    lines = _lines(response["lines"])
    observed_projects = tuple(
        sorted(
            (line["project_id"], line["project_code"], line["allocation_ratio"])
            for line in lines
        )
    )
    expected_projects = tuple(
        sorted(
            (item["project_id"], item["project_code"], item["allocation_ratio"])
            for item in request.body["projects"]
        )
    )
    if observed_projects != expected_projects:
        raise _drift("Allocation-plan Project set or ratios drifted")

    expected_selector_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-PLAN-RESOLVE-V1",
            "schema_version": request.body["schema_version"],
            "tenant_id": request.tenant_id,
            "company_id": request.company_id,
            "source_kind": request.body["source_kind"],
            "scope_type": request.body["scope_type"],
            "effective_on": request.body["effective_on"],
            "projects": list(request.body["projects"]),
        }
    )
    if response["selector_hash"] != expected_selector_hash:
        raise _drift("Allocation-plan selector hash drifted")
    expected_plan_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-PLAN-V1",
            **{
                name: response[name]
                for name in (
                    "tenant_id",
                    "company_id",
                    "plan_id",
                    "plan_revision",
                    "source_kind",
                    "scope_type",
                    "basis_kind",
                    "rule_release_hash",
                    "basis_source_ref",
                    "basis_source_hash",
                    "effective_start",
                    "effective_end",
                )
            },
            "lines": [dict(line) for line in lines],
        }
    )
    if response["plan_hash"] != expected_plan_hash:
        raise _drift("Allocation-plan hash drifted")
    expected_resolution_hash = semantic_sha256_hash_ref(
        {key: item for key, item in response.items() if key != "resolution_hash"}
    )
    if response["resolution_hash"] != expected_resolution_hash:
        raise _drift("Allocation-plan resolution hash drifted")
    return MappingProxyType({**response, "lines": tuple(lines)})


def _projects(value: object) -> list[Mapping[str, Any]]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or not 0 < len(value) <= 64
    ):
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_PROJECTS_INVALID", "bounded projects required"
        )
    admitted: list[Mapping[str, Any]] = []
    for item in value:
        project = _request_mapping(
            "project",
            item,
            frozenset({"project_id", "project_code", "allocation_ratio"}),
        )
        admitted.append(
            {
                "project_id": _request_uuid("project_id", project["project_id"]),
                "project_code": _request_pattern(
                    "project_code", project["project_code"], _PROJECT_CODE
                ),
                "allocation_ratio": _request_ratio(project["allocation_ratio"]),
            }
        )
    admitted.sort(key=lambda item: (item["project_code"], item["project_id"]))
    if len({item["project_id"] for item in admitted}) != len(admitted) or len(
        {item["project_code"] for item in admitted}
    ) != len(admitted):
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_PROJECTS_INVALID",
            "duplicate projects are prohibited",
        )
    if sum((Decimal(item["allocation_ratio"]) for item in admitted), Decimal()) != 1:
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_RATIO_INVALID", "project ratios must total one"
        )
    return admitted


def _lines(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise _drift("Allocation-plan lines are invalid")
    lines: list[Mapping[str, Any]] = []
    for index, item in enumerate(value, 1):
        line = _exact_mapping("line", item, _LINE_FIELDS)
        admitted = {
            "line_no": _positive_int("line_no", line["line_no"]),
            "project_id": _uuid("project_id", line["project_id"]),
            "project_code": _pattern(
                "project_code", line["project_code"], _PROJECT_CODE
            ),
            "work_code": None
            if line["work_code"] is None
            else _pattern("work_code", line["work_code"], _WORK_CODE),
            "basis_units": _pattern("basis_units", line["basis_units"], _BASIS_UNITS),
            "allocation_ratio": _ratio(line["allocation_ratio"]),
            "eligibility_hash": _hash("eligibility_hash", line["eligibility_hash"]),
            "confidentiality_class": _choice(
                "confidentiality_class", line["confidentiality_class"], _CONFIDENTIALITY
            ),
            "line_hash": _hash("line_hash", line["line_hash"]),
        }
        if admitted["line_no"] != index:
            raise _drift("Allocation-plan line order drifted")
        expected = semantic_sha256_hash_ref(
            {
                "domain": "EOS-COST-ALLOCATION-PLAN-LINE-V1",
                **{key: item for key, item in admitted.items() if key != "line_hash"},
            }
        )
        if admitted["line_hash"] != expected:
            raise _drift("Allocation-plan line hash drifted")
        lines.append(MappingProxyType(admitted))
    return lines


def _exact_mapping(field: str, value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _drift(f"{field} fields are not canonical")
    return dict(value)


def _request_mapping(
    field: str, value: object, fields: frozenset[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_REQUEST_INVALID",
            f"{field} fields are not canonical",
        )
    return dict(value)


def _scoped_id(field: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid("MYBEE_ALLOCATION_PLAN_REQUEST_INVALID", f"{field} is invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _drift(f"{field} is not a UUID") from exc


def _request_uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_REQUEST_INVALID", f"{field} is not a UUID"
        ) from exc


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _drift(f"{field} is unsupported")
    return value


def _request_choice(field: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_REQUEST_INVALID", f"{field} is unsupported"
        )
    return value


def _pattern(field: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _drift(f"{field} is invalid")
    return value


def _request_pattern(field: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _invalid("MYBEE_ALLOCATION_PLAN_REQUEST_INVALID", f"{field} is invalid")
    return value


def _ratio(value: object) -> str:
    return _pattern("allocation_ratio", value, _RATIO)


def _request_ratio(value: object) -> str:
    return _request_pattern("allocation_ratio", value, _RATIO)


def _date(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _drift(f"{field} is not an ISO date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _drift(f"{field} is not an ISO date") from exc


def _request_date(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_REQUEST_INVALID", f"{field} is not an ISO date"
        )
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _invalid(
            "MYBEE_ALLOCATION_PLAN_REQUEST_INVALID", f"{field} is not an ISO date"
        ) from exc


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _drift(f"{field} is not an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _drift(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise _drift(f"{field} must include timezone")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _drift(f"{field} must be positive")
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _drift(f"{field} is invalid") from exc


def _text(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _drift(f"{field} is invalid")
    return value


def _json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _drift("EOS allocation-plan response is not JSON") from exc
    if not isinstance(value, Mapping):
        raise _drift("EOS allocation-plan response must be an object")
    return value


def _optional_json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _invalid(error_code: str, detail: str) -> AllocationPlanConsumerError:
    return AllocationPlanConsumerError(error_code, detail, status_code=400)


def _drift(detail: str) -> AllocationPlanConsumerError:
    return AllocationPlanConsumerError(
        "MYBEE_ALLOCATION_PLAN_RESPONSE_INVALID", detail, status_code=502
    )
