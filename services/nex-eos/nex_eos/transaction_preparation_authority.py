from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from .accounting_periods import SqlAlchemyEosAccountingPeriodRepository
from .approval_policies import (
    ApprovalPolicySelection,
    SqlAlchemyEosApprovalPolicyRepository,
)
from .coa_operations import SqlAlchemyEosCoaOperationsRepository
from .legal_entities import SqlAlchemyEosLegalEntityRepository
from .project_authorization import EosProjectAuthorizationGate
from .projects import SqlAlchemyEosProjectRepository

TRANSACTION_PREPARATION_AUTHORITY_OPERATION = (
    "FINANCE.TRANSACTION_PREPARATION_AUTHORITY.RESOLVE"
)
TRANSACTION_PREPARATION_AUTHORITY_PATH = (
    "/internal/v2/finance/transaction-preparation-authority:resolve"
)
TRANSACTION_PREPARATION_AUTHORITY_REQUEST_SCHEMA = (
    "eos_transaction_preparation_authority_resolve.v1"
)
TRANSACTION_PREPARATION_AUTHORITY_RESPONSE_SCHEMA = (
    "eos_transaction_preparation_authority_resolution.v1"
)
TRANSACTION_PREPARATION_PROJECT_ACTION = "finance:voucher-candidate:create"

_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "requester_subject_id",
        "business_context_hash",
        "company_selector",
        "project_codes",
        "amount",
        "currency",
        "recognition_date",
        "debit_semantic_key",
        "credit_semantic_key",
        "capability_binding",
        "coordinator_binding",
        "correlation_id",
        "request_hash",
    }
)
_CAPABILITY_FIELDS = frozenset(
    {"capability_id", "capability_version", "capability_registration_hash"}
)
_COORDINATOR_FIELDS = frozenset(
    {
        "coordinator_id",
        "coordinator_version",
        "coordinator_registration_hash",
        "preparation_adapter_source_identity",
    }
)
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SEMANTIC_KEY = re.compile(r"^MB-COA-[A-Z0-9-]{1,112}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class EosTransactionPreparationAuthorityError(RuntimeError):
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


def _translate_source_errors(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except EosTransactionPreparationAuthorityError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if isinstance(status, int) and status in {404, 409, 422}:
                raise EosTransactionPreparationAuthorityError(
                    "EOS_TRANSACTION_PREPARATION_AUTHORITY_SOURCE_REJECTED",
                    "An authoritative EOS source rejected the resolution",
                    status_code=status,
                ) from exc
            raise _unavailable(
                "An authoritative EOS source is unavailable"
            ) from exc

    return guarded


class EosTransactionPreparationAuthorityService:
    """Resolves a bounded, read-only EOS/OA authority projection."""

    def __init__(
        self,
        *,
        legal_entities: SqlAlchemyEosLegalEntityRepository,
        projects: SqlAlchemyEosProjectRepository,
        accounts: SqlAlchemyEosCoaOperationsRepository,
        periods: SqlAlchemyEosAccountingPeriodRepository,
        approval_policies: SqlAlchemyEosApprovalPolicyRepository,
        project_authorizer: EosProjectAuthorizationGate,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._legal_entities = legal_entities
        self._projects = projects
        self._accounts = accounts
        self._periods = periods
        self._approval_policies = approval_policies
        self._project_authorizer = project_authorizer
        self._clock = clock or (lambda: datetime.now(UTC))

    @_translate_source_errors
    def resolve(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _admit_request(
            payload,
            tenant_id=tenant_id,
            requester_subject_id=requester_subject_id,
        )
        recognition_date = date.fromisoformat(request["recognition_date"])
        company = self._legal_entities.resolve_active_legal_entity(
            tenant_id=tenant_id,
            selector_kind=request["company_selector"]["kind"],
            selector_value=request["company_selector"]["value"],
            effective_on=recognition_date,
        )
        if company is None:
            raise _not_found("No active LegalEntity matches the company selector")
        company_id = str(company["company_id"])

        projects = self._resolve_projects(
            request=request,
            company_id=company_id,
            recognition_date=recognition_date,
        )
        debit = self._accounts.resolve_semantic_account(
            tenant_id=tenant_id,
            company_id=company_id,
            semantic_key=request["debit_semantic_key"],
            effective_on=recognition_date,
            currency=request["currency"],
        )
        credit = self._accounts.resolve_semantic_account(
            tenant_id=tenant_id,
            company_id=company_id,
            semantic_key=request["credit_semantic_key"],
            effective_on=recognition_date,
            currency=request["currency"],
        )
        if debit["account_ref"]["id"] == credit["account_ref"]["id"]:
            raise _conflict("Debit and credit semantic keys resolved to one Account")

        period = self._periods.find_period_for_date(
            tenant_id=tenant_id,
            company_id=company_id,
            posting_date=recognition_date,
        )
        if period is None:
            raise _not_found("No AccountingPeriod covers the recognition date")
        if period["state"] != "OPEN":
            raise _conflict("AccountingPeriod is not OPEN")

        primary_project = projects[0]["project"]
        business_policy_project_id = (
            str(primary_project["project_id"]) if len(projects) == 1 else None
        )
        amount = Decimal(request["amount"])
        business_policy = self._resolve_policy(
            tenant_id=tenant_id,
            amount=amount,
            effective_at=_effective_at(recognition_date),
            transaction_type="DOCUMENT_SIGNOFF",
            project_id=business_policy_project_id,
            account_ids=(),
        )
        accounting_policy = self._resolve_policy(
            tenant_id=tenant_id,
            amount=amount,
            effective_at=_effective_at(recognition_date),
            transaction_type="ACCOUNTING_POSTING",
            project_id=str(primary_project["project_id"]),
            account_ids=(
                str(debit["account_ref"]["id"]),
                str(credit["account_ref"]["id"]),
            ),
        )
        authority_effective_at = _aware(self._clock())
        authority = _authority_projection(
            request=request,
            company=company,
            projects=projects,
            debit=debit,
            credit=credit,
            business_policy=business_policy,
            accounting_policy=accounting_policy,
            authority_effective_at=authority_effective_at,
        )
        accounting_period = {
            "period_id": str(period["period_id"]),
            "fiscal_year": int(period["fiscal_year"]),
            "period_no": int(period["period_no"]),
            "state": str(period["state"]),
            "version": int(period["version"]),
            "start_date": str(period["start_date"]),
            "end_date": str(period["end_date"]),
        }
        accounting_period["evidence_hash"] = semantic_sha256_hash_ref(
            {"domain": "EOS-ACCOUNTING-PERIOD-AUTHORITY-V1", **accounting_period}
        )
        result = {
            "schema_version": TRANSACTION_PREPARATION_AUTHORITY_RESPONSE_SCHEMA,
            "operation": TRANSACTION_PREPARATION_AUTHORITY_OPERATION,
            "request_hash": request["request_hash"],
            "authority": authority,
            "accounting_period": accounting_period,
        }
        result["resolution_hash"] = semantic_sha256_hash_ref(
            {"domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-RESOLUTION-V1", **result}
        )
        return result

    def _resolve_projects(
        self,
        *,
        request: Mapping[str, Any],
        company_id: str,
        recognition_date: date,
    ) -> list[dict[str, Any]]:
        result = []
        for project_code in request["project_codes"]:
            project = self._projects.get_project_by_code(
                tenant_id=request["tenant_id"],
                project_code=project_code,
                active_only=True,
            )
            if project is None:
                raise _not_found(f"Active Project {project_code} was not found")
            binding = self._legal_entities.get_effective_project_company_binding(
                tenant_id=request["tenant_id"],
                project_id=str(project["project_id"]),
                effective_on=recognition_date,
            )
            if binding is None or str(binding["company_id"]) != company_id:
                raise _conflict(
                    f"Project {project_code} is not bound to the resolved company"
                )
            try:
                authorization = self._project_authorizer.authorize(
                    tenant_id=request["tenant_id"],
                    subject_id=request["requester_subject_id"],
                    project_id=str(project["project_id"]),
                    expected_project_code=project_code,
                    action=TRANSACTION_PREPARATION_PROJECT_ACTION,
                    correlation_id=f"{request['correlation_id']}:{project_code}",
                )
            except Exception as exc:
                status = int(getattr(exc, "status_code", 503))
                raise EosTransactionPreparationAuthorityError(
                    "EOS_TRANSACTION_PREPARATION_PROJECT_AUTHORITY_DENIED"
                    if status < 500
                    else "EOS_TRANSACTION_PREPARATION_PROJECT_AUTHORITY_UNAVAILABLE",
                    f"Fresh Project authority failed for {project_code}",
                    status_code=status,
                    retryable=status >= 500,
                ) from exc
            result.append(
                {
                    "project": project,
                    "authorization": authorization,
                }
            )
        return result

    def _resolve_policy(
        self,
        *,
        tenant_id: str,
        amount: Decimal,
        effective_at: datetime,
        transaction_type: str,
        project_id: str,
        account_ids: Sequence[str],
    ) -> dict[str, Any]:
        policy = self._approval_policies.resolve_policy(
            ApprovalPolicySelection(
                tenant_id=tenant_id,
                approval_domain="BUSINESS_FORMAL",
                risk_level=None,
                amount=amount,
                transaction_type=transaction_type,
                effective_at=effective_at,
                project_id=project_id,
                account_ids=account_ids,
            )
        )
        if policy is None:
            raise _not_found(
                f"No active {transaction_type} ApprovalPolicy matches the authority"
            )
        return policy


def _admit_request(
    value: Mapping[str, Any], *, tenant_id: str, requester_subject_id: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
        raise _invalid("Authority request fields drifted")
    request = dict(value)
    tenant = _scoped_id("tenant_id", tenant_id)
    subject = _scoped_id("requester_subject_id", requester_subject_id)
    if (
        request["schema_version"] != TRANSACTION_PREPARATION_AUTHORITY_REQUEST_SCHEMA
        or request["tenant_id"] != tenant
        or request["requester_subject_id"] != subject
    ):
        raise _invalid("Authority request identity drifted")
    _hash_ref("business_context_hash", request["business_context_hash"])
    selector = _exact_mapping(
        "company_selector", request["company_selector"], {"kind", "value"}
    )
    if selector["kind"] not in {"CODE", "NAME", "CODE_OR_NAME"}:
        raise _invalid("Company selector kind is invalid")
    _text("company_selector.value", selector["value"], 160)
    request["company_selector"] = selector
    project_codes = request["project_codes"]
    if (
        not isinstance(project_codes, list)
        or not 1 <= len(project_codes) <= 12
        or any(not isinstance(item, str) or not _PROJECT_CODE.fullmatch(item) for item in project_codes)
        or len(set(project_codes)) != len(project_codes)
    ):
        raise _invalid("Project Codes are invalid")
    _amount(request["amount"])
    if not isinstance(request["currency"], str) or not _CURRENCY.fullmatch(
        request["currency"]
    ):
        raise _invalid("Currency is invalid")
    try:
        date.fromisoformat(str(request["recognition_date"]))
    except ValueError as exc:
        raise _invalid("Recognition date is invalid") from exc
    for field in ("debit_semantic_key", "credit_semantic_key"):
        if not isinstance(request[field], str) or not _SEMANTIC_KEY.fullmatch(
            request[field]
        ):
            raise _invalid(f"{field} is invalid")
    if request["debit_semantic_key"] == request["credit_semantic_key"]:
        raise _invalid("Debit and credit semantic keys must differ")
    capability = _exact_mapping(
        "capability_binding", request["capability_binding"], _CAPABILITY_FIELDS
    )
    coordinator = _exact_mapping(
        "coordinator_binding", request["coordinator_binding"], _COORDINATOR_FIELDS
    )
    _hash_ref(
        "capability_registration_hash", capability["capability_registration_hash"]
    )
    _hash_ref(
        "coordinator_registration_hash",
        coordinator["coordinator_registration_hash"],
    )
    for field, item in (*capability.items(), *coordinator.items()):
        if not field.endswith("hash"):
            _text(field, item, 512)
    request["capability_binding"] = capability
    request["coordinator_binding"] = coordinator
    _scoped_id("correlation_id", request["correlation_id"])
    expected_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-REQUEST-V1",
            **{key: item for key, item in request.items() if key != "request_hash"},
        }
    )
    if request["request_hash"] != expected_hash:
        raise _invalid("Authority request hash does not match content")
    return request


def _authority_projection(
    *,
    request: Mapping[str, Any],
    company: Mapping[str, Any],
    projects: Sequence[Mapping[str, Any]],
    debit: Mapping[str, Any],
    credit: Mapping[str, Any],
    business_policy: Mapping[str, Any],
    accounting_policy: Mapping[str, Any],
    authority_effective_at: datetime,
) -> dict[str, Any]:
    project_refs = [
        {
            "project_id": str(item["project"]["project_id"]),
            "project_code": str(item["project"]["project_code"]),
            "project_version": int(item["project"]["version"]),
        }
        for item in projects
    ]
    project_authorizations = [
        {
            "project_code": str(item["authorization"].project_code),
            "decision_ref": str(item["authorization"].decision_ref),
            "revision_hash": _canonical_hash_ref(
                "authorization_revision_hash",
                item["authorization"].authorization_revision_hash,
            ),
            "source_version": int(item["authorization"].source_version),
        }
        for item in projects
    ]
    project_authorization_revision_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-TRANSACTION-PROJECT-AUTHORITY-SET-V1",
            "tenant_id": request["tenant_id"],
            "requester_subject_id": request["requester_subject_id"],
            "project_authorizations": project_authorizations,
        }
    )
    company_evidence = {
        "tenant_id": request["tenant_id"],
        "company_id": str(company["company_id"]),
        "company_code": str(company["company_code"]),
        "functional_currency": str(company["functional_currency"]),
        "status": str(company["status"]),
        "effective_from": str(company["effective_from"]),
        "version": int(company["version"]),
    }
    authority = {
        "schema_version": "nex.mybee.m1-preparation-authority.v1",
        "tenant_id": request["tenant_id"],
        "requester_subject_id": request["requester_subject_id"],
        "company_id": str(company["company_id"]),
        "company_code": str(company["company_code"]),
        "company_selector_kind": request["company_selector"]["kind"],
        "company_selector_value": request["company_selector"]["value"],
        "company_version": int(company["version"]),
        "company_evidence_hash": semantic_sha256_hash_ref(company_evidence),
        "functional_currency": str(company["functional_currency"]),
        "primary_project_id": project_refs[0]["project_id"],
        "primary_project_code": project_refs[0]["project_code"],
        "project_refs": project_refs,
        "project_authorizations": project_authorizations,
        "debit_account_id": str(debit["account_ref"]["id"]),
        "debit_semantic_key": request["debit_semantic_key"],
        "debit_account_evidence_hash": str(debit["evidence_hash"]),
        "credit_account_id": str(credit["account_ref"]["id"]),
        "credit_semantic_key": request["credit_semantic_key"],
        "credit_account_evidence_hash": str(credit["evidence_hash"]),
        "business_approval_policy_id": str(business_policy["approval_policy_id"]),
        "business_approval_policy_version": int(business_policy["version"]),
        "business_approval_policy_hash": str(business_policy["policy_hash"]),
        "accounting_approval_policy_id": str(accounting_policy["approval_policy_id"]),
        "accounting_approval_policy_version": int(accounting_policy["version"]),
        "accounting_approval_policy_hash": str(accounting_policy["policy_hash"]),
        "project_authorization_ref": (
            "oa.project-authority-set:"
            + project_authorization_revision_hash.removeprefix("sha256:")
        ),
        "project_authorization_revision_hash": project_authorization_revision_hash,
        "authority_effective_at": authority_effective_at.isoformat().replace(
            "+00:00", "Z"
        ),
    }
    authority["authority_hash"] = semantic_sha256_hash_ref(authority)
    return authority


def _exact_mapping(name: str, value: object, fields: set[str] | frozenset[str]):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise _invalid(f"{name} fields drifted")
    return dict(value)


def _hash_ref(name: str, value: object) -> str:
    try:
        return validate_hash_ref(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} is invalid") from exc


def _canonical_hash_ref(name: str, value: object) -> str:
    candidate = str(value)
    if re.fullmatch(r"[0-9a-f]{64}", candidate):
        candidate = f"sha256:{candidate}"
    return _hash_ref(name, candidate)


def _amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
        canonical = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid("Amount is invalid") from exc
    if not amount.is_finite() or amount <= 0 or amount != canonical:
        raise _invalid("Amount must be a positive value with two decimals")
    return amount


def _effective_at(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, 12, tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _unavailable("Authority clock must return an aware datetime")
    return value.astimezone(UTC)


def _scoped_id(name: str, value: object) -> str:
    text = str(value).strip()
    if not _SCOPED_ID.fullmatch(text):
        raise _invalid(f"{name} is invalid")
    return text


def _text(name: str, value: object, maximum: int) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum:
        raise _invalid(f"{name} is invalid")
    return text


def _invalid(detail: str) -> EosTransactionPreparationAuthorityError:
    return EosTransactionPreparationAuthorityError(
        "EOS_TRANSACTION_PREPARATION_AUTHORITY_REQUEST_INVALID",
        detail,
        status_code=422,
    )


def _not_found(detail: str) -> EosTransactionPreparationAuthorityError:
    return EosTransactionPreparationAuthorityError(
        "EOS_TRANSACTION_PREPARATION_AUTHORITY_NOT_FOUND",
        detail,
        status_code=404,
    )


def _conflict(detail: str) -> EosTransactionPreparationAuthorityError:
    return EosTransactionPreparationAuthorityError(
        "EOS_TRANSACTION_PREPARATION_AUTHORITY_CONFLICT",
        detail,
        status_code=409,
    )


def _unavailable(detail: str) -> EosTransactionPreparationAuthorityError:
    return EosTransactionPreparationAuthorityError(
        "EOS_TRANSACTION_PREPARATION_AUTHORITY_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


__all__ = [
    "TRANSACTION_PREPARATION_AUTHORITY_OPERATION",
    "TRANSACTION_PREPARATION_AUTHORITY_PATH",
    "TRANSACTION_PREPARATION_AUTHORITY_REQUEST_SCHEMA",
    "TRANSACTION_PREPARATION_AUTHORITY_RESPONSE_SCHEMA",
    "EosTransactionPreparationAuthorityError",
    "EosTransactionPreparationAuthorityService",
]
