"""Strict MyBee consumer for Journal cost admission and allocation execution."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

JOURNAL_GET_OPERATION = "FINANCE.JOURNAL.GET"
SOURCE_POOL_ADMIT_OPERATION = "FINANCE.COST_SOURCE_POOL.ADMIT"
ALLOCATION_RUN_OPERATION = "FINANCE.COST_ALLOCATION.RUN"
ALLOCATION_VERIFY_OPERATION = "FINANCE.COST_ALLOCATION.VERIFY"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AMOUNT = re.compile(r"^-?[0-9]+\.[0-9]{4}$")
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
_POOL_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "idempotency_disposition",
        "tenant_id",
        "company_id",
        "pool_id",
        "journal_id",
        "journal_line_no",
        "eligible_component_id",
        "source_business_operation_id",
        "source_project_id",
        "source_project_code",
        "source_kind",
        "allocation_mode",
        "source_amount_functional",
        "eligible_amount_functional",
        "functional_currency",
        "account_id",
        "account_category",
        "monetary_class",
        "recognition_date",
        "recognized_at",
        "period_id",
        "source_record_ref",
        "source_hash",
        "eligibility_policy_hash",
        "pool_state",
        "source_journal_hash",
        "created_at",
    }
)
_BATCH_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "idempotency_disposition",
        "tenant_id",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "commit_state",
        "business_result_ref",
        "company_id",
        "batch_id",
        "plan_id",
        "plan_revision",
        "period_id",
        "source_set_hash",
        "functional_currency",
        "allocated_total",
        "unallocated_total",
        "reconciliation_hash",
        "line_count",
        "pool_count",
        "committed_at",
        "outbox",
    }
)
_VERIFY_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "tenant_id",
        "business_operation_id",
        "commit_state",
        "reconciliation_status",
        "verification_status",
        "retry_disposition",
        "batch",
        "conservation",
        "reversed_pool_ids",
        "outbox",
    }
)


class CostAllocationConsumerError(RuntimeError):
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
class CostAllocationProviderRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    company_id: str
    correlation_id: str
    subject_id: str | None = None
    body: Mapping[str, Any] | None = None


class CostAllocationProviderTransport(Protocol):
    def send(self, request: CostAllocationProviderRequest) -> Mapping[str, Any]: ...


class HttpCostAllocationProviderTransport:
    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid("MYBEE_ALLOCATION_BASE_URL_INVALID", "http(s) URL required")
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid(
                "MYBEE_ALLOCATION_SERVICE_TOKEN_MISSING", "service token is required"
            )
        if timeout_seconds <= 0:
            raise _invalid("MYBEE_ALLOCATION_TIMEOUT_INVALID", "positive timeout required")
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: CostAllocationProviderRequest) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._service_token}",
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "X-NeX-Tenant-Id": request.tenant_id,
            "X-NeX-Company-Id": request.company_id,
            "X-Correlation-Id": request.correlation_id,
            "X-NeX-Correlation-Id": request.correlation_id,
        }
        if request.subject_id is not None:
            headers["X-NeX-Subject-Id"] = request.subject_id
        data = None
        if request.body is not None:
            data = json.dumps(dict(request.body), sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        outgoing = Request(
            urljoin(self._base_url, request.path.lstrip("/")),
            method=request.method,
            data=data,
            headers=headers,
        )
        try:
            with urlopen(outgoing, timeout=self._timeout_seconds) as response:
                return _json_object(response.read())
        except HTTPError as exc:
            problem = _optional_json_object(exc.read())
            raise CostAllocationConsumerError(
                str(problem.get("error_code", "EOS_COST_ALLOCATION_REJECTED")),
                "EOS rejected the Journal allocation operation",
                status_code=exc.code,
                retryable=bool(problem.get("retryable", exc.code >= 500)),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CostAllocationConsumerError(
                "EOS_COST_ALLOCATION_UNAVAILABLE",
                "EOS Journal allocation endpoint is unavailable",
                status_code=503,
                retryable=True,
            ) from exc


class NexCostAllocationClient:
    """Runs only authority-bound, fully conserved allocation operations."""

    def __init__(self, transport: CostAllocationProviderTransport) -> None:
        self._transport = transport

    def admit_source_pool(
        self,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
        subject_id: str,
        correlation_id: str,
        source_record_line_ref: str,
        source_kind: str,
        allocation_mode: str,
    ) -> Mapping[str, Any]:
        identity = _request_identity(
            tenant_id, company_id, correlation_id, subject_id=subject_id
        )
        journal = self._transport.send(
            CostAllocationProviderRequest(
                "GET",
                f"/internal/v2/finance/journals/{_uuid('journal_id', journal_id)}",
                JOURNAL_GET_OPERATION,
                **identity,
            )
        )
        line_no = _select_source_line(
            journal,
            tenant_id=identity["tenant_id"],
            company_id=identity["company_id"],
            journal_id=journal_id,
            source_record_line_ref=source_record_line_ref,
        )
        request = CostAllocationProviderRequest(
            "POST",
            f"/internal/v2/finance/journals/{_uuid('journal_id', journal_id)}"
            f"/lines/{line_no}/cost-source-pool",
            SOURCE_POOL_ADMIT_OPERATION,
            body={
                "schema_version": "eos_cost_source_pool_admit.v1",
                "source_kind": _choice("source_kind", source_kind, _SOURCE_KINDS),
                "allocation_mode": _choice(
                    "allocation_mode", allocation_mode, {"MANAGEMENT_ALLOCATION"}
                ),
            },
            **identity,
        )
        return _admit_source_pool(self._transport.send(request), request=request)

    def run_verified(
        self,
        *,
        tenant_id: str,
        company_id: str,
        correlation_id: str,
        source_pool: Mapping[str, Any],
        allocation_authority: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        command = build_cost_allocation_run(
            tenant_id=tenant_id,
            company_id=company_id,
            source_pool=source_pool,
            allocation_authority=allocation_authority,
        )
        identity = _request_identity(tenant_id, company_id, correlation_id)
        batch = _admit_batch(
            self._transport.send(
                CostAllocationProviderRequest(
                    "POST",
                    "/internal/v2/finance/cost-allocation-batches",
                    ALLOCATION_RUN_OPERATION,
                    body=command,
                    **identity,
                )
            ),
            command=command,
        )
        verification = _admit_verification(
            self._transport.send(
                CostAllocationProviderRequest(
                    "GET",
                    f"/internal/v2/finance/cost-allocation-batches/"
                    f"{command['batch_id']}/verification",
                    ALLOCATION_VERIFY_OPERATION,
                    **identity,
                )
            ),
            command=command,
            batch=batch,
            source_pool=source_pool,
        )
        return batch, verification


def build_cost_allocation_run(
    *,
    tenant_id: str,
    company_id: str,
    source_pool: Mapping[str, Any],
    allocation_authority: Mapping[str, Any],
) -> Mapping[str, Any]:
    tenant = _scoped("tenant_id", tenant_id, 128)
    company = _uuid("company_id", company_id)
    pool = _exact("source_pool", source_pool, _POOL_FIELDS)
    if (
        pool.get("tenant_id") != tenant
        or pool.get("company_id") != company
        or pool.get("allocation_mode") != "MANAGEMENT_ALLOCATION"
        or pool.get("pool_state") != "OPEN"
    ):
        raise _drift("SourcePool is not open allocation authority")
    authority = dict(allocation_authority)
    if (
        authority.get("schema_version")
        not in {
            "mybee.approved_allocation_plan_authority.v1",
            "mybee.approved_allocation_plan_authority.v2",
        }
        or authority.get("stage") != "READY_FOR_ALLOCATION"
        or authority.get("tenant_id") != tenant
        or authority.get("company_id") != company
    ):
        raise _drift("AllocationPlan authority checkpoint is invalid")
    authority_pool = authority.get("source_pool")
    plan = authority.get("allocation_plan")
    if (
        not isinstance(authority_pool, Mapping)
        or authority_pool.get("pool_id") != pool.get("pool_id")
        or authority_pool.get("source_hash") != pool.get("source_hash")
        or not isinstance(plan, Mapping)
    ):
        raise _drift("Allocation authority differs from the admitted SourcePool")
    checkpoint_hash = _hash("checkpoint_hash", authority.get("checkpoint_hash"))
    batch_id = str(
        uuid5(NAMESPACE_URL, f"nex:cost-allocation-batch:{tenant}:{checkpoint_hash}")
    )
    operation_id = str(
        uuid5(NAMESPACE_URL, f"nex:cost-allocation-operation:{tenant}:{checkpoint_hash}")
    )
    business_payload = {
        "schema_version": "eos_cost_allocation_run.v1",
        "tenant_id": tenant,
        "company_id": company,
        "batch_id": batch_id,
        "plan_id": _uuid("plan_id", plan.get("plan_id")),
        "plan_revision": _positive_int("plan_revision", plan.get("plan_revision")),
        "period_id": _uuid("period_id", pool.get("period_id")),
        "functional_currency": _pattern(
            "functional_currency", pool.get("functional_currency"), _CURRENCY
        ),
        "currency_scale": 4,
        "sources": [
            {
                "pool_id": _uuid("pool_id", pool.get("pool_id")),
                "unallocated_amount_functional": "0.0000",
            }
        ],
    }
    payload_hash = semantic_sha256_hash_ref(
        {"domain": "EOS-COST-ALLOCATION-RUN-V1", **business_payload}
    )
    command = {
        key: value
        for key, value in business_payload.items()
        if key not in {"tenant_id", "company_id"}
    }
    command.update(
        business_operation_id=operation_id,
        idempotency_key=f"mybee-allocation:{batch_id}",
        payload_hash=payload_hash,
    )
    return MappingProxyType(command)


def _select_source_line(
    value: object,
    *,
    tenant_id: str,
    company_id: str,
    journal_id: str,
    source_record_line_ref: str,
) -> int:
    journal = dict(value) if isinstance(value, Mapping) else {}
    header = journal.get("header")
    lines = journal.get("lines")
    if (
        journal.get("schema_version") != "eos_posted_journal.v1"
        or journal.get("operation_id") != JOURNAL_GET_OPERATION
        or not isinstance(header, Mapping)
        or header.get("tenant_id") != tenant_id
        or header.get("company_id") != company_id
        or header.get("journal_id") != _uuid("journal_id", journal_id)
        or header.get("state") != "POSTED"
        or not isinstance(lines, list)
        or header.get("line_count") != len(lines)
    ):
        raise _drift("PostedJournal source authority drifted")
    ref = _scoped("source_record_line_ref", source_record_line_ref, 256)
    matches = [
        item
        for item in lines
        if isinstance(item, Mapping)
        and item.get("source_record_line_ref") == ref
        and item.get("tenant_id") == tenant_id
        and item.get("company_id") == company_id
        and item.get("journal_id") == journal_id
    ]
    if len(matches) != 1:
        raise _drift("PostedJournal has no unique admitted cost source line")
    return _positive_int("journal_line_no", matches[0].get("line_no"))


def _admit_source_pool(
    value: object, *, request: CostAllocationProviderRequest
) -> Mapping[str, Any]:
    pool = _exact("source_pool", value, _POOL_FIELDS)
    path_parts = request.path.strip("/").split("/")
    expected_journal_id = path_parts[4] if len(path_parts) >= 5 else None
    if (
        pool.get("schema_version") != "eos_cost_source_pool.v1"
        or pool.get("operation") != SOURCE_POOL_ADMIT_OPERATION
        or pool.get("idempotency_disposition") not in {"CREATED", "EXACT_REPLAY"}
        or pool.get("tenant_id") != request.tenant_id
        or pool.get("company_id") != request.company_id
        or pool.get("journal_id") != expected_journal_id
        or pool.get("source_kind") != request.body["source_kind"]
        or pool.get("allocation_mode") != request.body["allocation_mode"]
        or pool.get("pool_state") != "OPEN"
    ):
        raise _drift("CostSourcePool response lineage drifted")
    for name in (
        "pool_id",
        "source_business_operation_id",
        "source_project_id",
        "account_id",
        "period_id",
    ):
        _uuid(name, pool.get(name))
    _project_code(pool.get("source_project_code"))
    _amount("eligible_amount_functional", pool.get("eligible_amount_functional"))
    for name in ("source_hash", "source_journal_hash", "eligibility_policy_hash"):
        _hash(name, pool.get(name))
    return MappingProxyType(pool)


def _admit_batch(value: object, *, command: Mapping[str, Any]) -> Mapping[str, Any]:
    batch = _exact("allocation_batch", value, _BATCH_FIELDS)
    expected = {
        "schema_version": "eos_cost_allocation_batch.v1",
        "operation": ALLOCATION_RUN_OPERATION,
        "business_operation_id": command["business_operation_id"],
        "idempotency_key": command["idempotency_key"],
        "payload_hash": command["payload_hash"],
        "commit_state": "COMMITTED",
        "batch_id": command["batch_id"],
        "plan_id": command["plan_id"],
        "plan_revision": command["plan_revision"],
        "period_id": command["period_id"],
        "functional_currency": command["functional_currency"],
    }
    if any(batch.get(name) != expected_value for name, expected_value in expected.items()):
        raise _drift("Cost Allocation batch lineage drifted")
    if batch.get("idempotency_disposition") not in {"CREATED", "EXACT_REPLAY"}:
        raise _drift("Cost Allocation replay disposition drifted")
    if (
        _amount("unallocated_total", batch.get("unallocated_total")) != Decimal(0)
        or _positive_int("line_count", batch.get("line_count")) < 1
        or batch.get("pool_count") != len(command["sources"])
    ):
        raise _drift("Cost Allocation did not fully conserve the source set")
    for name in ("source_set_hash", "reconciliation_hash"):
        _hash(name, batch.get(name))
    return MappingProxyType(batch)


def _admit_verification(
    value: object,
    *,
    command: Mapping[str, Any],
    batch: Mapping[str, Any],
    source_pool: Mapping[str, Any],
) -> Mapping[str, Any]:
    result = _exact("allocation_verification", value, _VERIFY_FIELDS)
    verified_batch = result.get("batch")
    conservation = result.get("conservation")
    if (
        result.get("schema_version") != "eos_cost_allocation_reconciliation.v1"
        or result.get("operation") != ALLOCATION_VERIFY_OPERATION
        or result.get("business_operation_id") != command["business_operation_id"]
        or result.get("commit_state") != "COMMITTED"
        or result.get("reconciliation_status") != "COMMITTED_CONFIRMED"
        or result.get("verification_status") != "VERIFIED"
        or result.get("retry_disposition") != "DO_NOT_RERUN"
        or result.get("reversed_pool_ids") != []
        or not isinstance(verified_batch, Mapping)
        or verified_batch.get("batch_id") != batch["batch_id"]
        or verified_batch.get("reconciliation_hash") != batch["reconciliation_hash"]
        or not isinstance(conservation, list)
        or len(conservation) != 1
    ):
        raise _drift("Cost Allocation verification is not authoritative")
    item = conservation[0]
    eligible = _amount(
        "eligible_amount_functional", source_pool.get("eligible_amount_functional")
    )
    if (
        not isinstance(item, Mapping)
        or item.get("pool_id") != source_pool.get("pool_id")
        or item.get("source_hash") != source_pool.get("source_hash")
        or _amount("eligible_amount_functional", item.get("eligible_amount_functional"))
        != eligible
        or _amount("direct_amount_functional", item.get("direct_amount_functional"))
        != Decimal(0)
        or _amount(
            "allocated_amount_functional", item.get("allocated_amount_functional")
        )
        != eligible
        or _amount(
            "unallocated_amount_functional", item.get("unallocated_amount_functional")
        )
        != Decimal(0)
    ):
        raise _drift("Cost Allocation conservation evidence drifted")
    return MappingProxyType(
        {
            **result,
            "batch": MappingProxyType(dict(verified_batch)),
            "conservation": tuple(MappingProxyType(dict(item)) for item in conservation),
        }
    )


def _request_identity(
    tenant_id: object,
    company_id: object,
    correlation_id: object,
    *,
    subject_id: object | None = None,
) -> dict[str, Any]:
    return {
        "tenant_id": _scoped("tenant_id", tenant_id, 128),
        "company_id": _uuid("company_id", company_id),
        "correlation_id": _scoped("correlation_id", correlation_id, 128),
        "subject_id": (
            None if subject_id is None else _scoped("subject_id", subject_id, 128)
        ),
    }


def _exact(name: str, value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _drift(f"{name} fields drifted")
    return dict(value)


def _json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _drift("EOS allocation response is not JSON") from exc
    if not isinstance(value, Mapping):
        raise _drift("EOS allocation response is not an object")
    return value


def _optional_json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _scoped(name: str, value: object, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum or _SCOPED_ID.fullmatch(text) is None:
        raise _invalid("MYBEE_ALLOCATION_ARGUMENT_INVALID", f"{name} is invalid")
    return text


def _uuid(name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(
            "MYBEE_ALLOCATION_ARGUMENT_INVALID", f"{name} must be a UUID"
        ) from exc


def _positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _drift(f"{name} must be a positive integer")
    return value


def _choice(name: str, value: object, choices: set[str] | frozenset[str]) -> str:
    text = str(value or "")
    if text not in choices:
        raise _invalid("MYBEE_ALLOCATION_ARGUMENT_INVALID", f"{name} is invalid")
    return text


def _pattern(name: str, value: object, pattern: re.Pattern[str]) -> str:
    text = str(value or "")
    if pattern.fullmatch(text) is None:
        raise _drift(f"{name} is invalid")
    return text


def _project_code(value: object) -> str:
    return _pattern("project_code", value, _PROJECT_CODE)


def _hash(name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _drift(f"{name} is invalid") from exc


def _amount(name: str, value: object) -> Decimal:
    if not isinstance(value, str) or _AMOUNT.fullmatch(value) is None:
        raise _drift(f"{name} is invalid")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise _drift(f"{name} is invalid") from exc
    return amount


def _invalid(code: str, detail: str) -> CostAllocationConsumerError:
    return CostAllocationConsumerError(code, detail, status_code=422)


def _drift(detail: str) -> CostAllocationConsumerError:
    return CostAllocationConsumerError(
        "EOS_COST_ALLOCATION_RESPONSE_DRIFT", detail, status_code=502
    )
