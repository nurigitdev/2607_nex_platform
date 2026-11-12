from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from .account_catalog import EosAccountCatalogError
from .accounting_periods import EosAccountingPeriodError
from .accounting_rules import AccountingRuleError, functionalize_candidate_lines
from .fx_rates import EosFxRateError
from .legal_entities import EosLegalEntityError
from .voucher_candidates import EosVoucherCandidateError

VALIDATE_VOUCHER_CANDIDATE_OPERATION = "FINANCE.VOUCHER_CANDIDATE.VALIDATE"
_ALLOWED_CANDIDATE_STATES = frozenset({"DRAFT", "RETURNED_FOR_CORRECTION"})


class EosCandidateValidationError(RuntimeError):
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


class EosCandidateValidationService:
    def __init__(
        self,
        *,
        candidates: Any,
        legal_entities: Any,
        periods: Any,
        account_catalog: Any,
        fx_rates: Any,
    ) -> None:
        self._candidates = candidates
        self._legal_entities = legal_entities
        self._periods = periods
        self._account_catalog = account_catalog
        self._fx_rates = fx_rates

    def validate(self, candidate_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _request(candidate_id, payload)
        try:
            candidate = self._candidates.get(
                tenant_id=request["tenant_id"], candidate_id=request["candidate_id"]
            )
            if candidate is None:
                raise EosCandidateValidationError(
                    "EOS_VOUCHER_CANDIDATE_NOT_FOUND",
                    "VoucherCandidate was not found in tenant scope.",
                    status_code=404,
                )
            revision = candidate["revision"]
            _require_current_candidate(request, candidate, revision)
            recognition_date = _stored_date(
                "candidate.recognition_date", candidate["recognition_date"]
            )
            company = self._legal_entities.get_legal_entity(
                tenant_id=request["tenant_id"],
                company_id=str(candidate["company_id"]),
                effective_on=recognition_date,
                active_only=True,
            )
            if not company:
                raise _rejected(
                    "EOS_CANDIDATE_COMPANY_UNAVAILABLE",
                    "An active LegalEntity is required on the recognition date.",
                )
            period = self._periods.find_period_for_date(
                tenant_id=request["tenant_id"],
                company_id=str(candidate["company_id"]),
                posting_date=recognition_date,
            )
            if period is None or period["state"] != "OPEN":
                raise _rejected(
                    "EOS_CANDIDATE_PERIOD_NOT_OPEN",
                    "VoucherCandidate recognition requires one OPEN AccountingPeriod.",
                )
            catalog = self._account_catalog.get_effective_catalog(
                tenant_id=request["tenant_id"],
                company_id=str(candidate["company_id"]),
                effective_on=recognition_date,
            )
            if catalog is None:
                raise _rejected(
                    "EOS_CANDIDATE_ACCOUNT_CATALOG_UNAVAILABLE",
                    "A published effective account catalog is required.",
                )
            used_policies = _require_accounts(candidate, catalog)
            fx_evidence = self._resolve_fx(
                request=request,
                candidate=candidate,
                functional_currency=str(company["functional_currency"]),
                recognition_date=recognition_date,
            )
            functionalized = functionalize_candidate_lines(
                candidate["lines"],
                transaction_currency=str(candidate["transaction_currency"]),
                functional_currency=str(company["functional_currency"]),
                normalized_rate=fx_evidence["normalized_rate"],
            )
        except EosCandidateValidationError:
            raise
        except AccountingRuleError as exc:
            raise _rejected(exc.error_code, exc.detail) from exc
        except (
            EosVoucherCandidateError,
            EosLegalEntityError,
            EosAccountingPeriodError,
            EosAccountCatalogError,
            EosFxRateError,
        ) as exc:
            raise EosCandidateValidationError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc

        posting_rule = catalog["posting_rule"]
        account_policy_set_hash = semantic_sha256_hash_ref(
            {
                "domain": "EOS-CANDIDATE-ACCOUNT-POLICY-SET-V1",
                "policies": used_policies,
            }
        )
        fx_rate_set_hash = semantic_sha256_hash_ref(
            {"domain": "EOS-CANDIDATE-FX-RATE-SET-V1", **fx_evidence}
        )
        evidence = {
            "candidate_id": request["candidate_id"],
            "candidate_hash": revision["candidate_hash"],
            "revision_no": revision["revision_no"],
            "accounting_period_id": period["period_id"],
            "posting_rule_release_hash": posting_rule["rule_hash"],
            "account_policy_set_hash": account_policy_set_hash,
            "fx_rate_set_hash": fx_rate_set_hash,
            "accounting_rule_profile_hash": functionalized.rule_profile_hash,
            "lines": list(functionalized.lines),
        }
        return {
            "schema_version": "eos_voucher_candidate_validation.v1",
            "operation": VALIDATE_VOUCHER_CANDIDATE_OPERATION,
            "status": "PASS",
            "tenant_id": request["tenant_id"],
            "candidate_ref": {
                "type": "eos.voucher_candidate",
                "id": request["candidate_id"],
            },
            "revision_ref": {
                "type": "eos.voucher_candidate_revision",
                "id": str(revision["revision_id"]),
                "revision_no": revision["revision_no"],
                "hash": revision["candidate_hash"],
            },
            "project_ref": {
                "type": "eos.project",
                "id": str(candidate["project_id"]),
                "code": str(candidate["project_code"]),
            },
            "company_id": str(candidate["company_id"]),
            "accounting_period_id": str(period["period_id"]),
            "recognition_date": recognition_date.isoformat(),
            "transaction_currency": str(candidate["transaction_currency"]),
            "functional_currency": str(company["functional_currency"]),
            "posting_rule_release_hash": str(posting_rule["rule_hash"]),
            "account_policy_set_hash": account_policy_set_hash,
            "fx_rate_set_hash": fx_rate_set_hash,
            "fx_evidence": fx_evidence,
            "lines": list(functionalized.lines),
            "totals": {
                "debit_original": functionalized.debit_original,
                "credit_original": functionalized.credit_original,
                "debit_functional": functionalized.debit_functional,
                "credit_functional": functionalized.credit_functional,
            },
            "validation_hash": semantic_sha256_hash_ref(
                {"domain": "EOS-VOUCHER-CANDIDATE-VALIDATION-V1", **evidence}
            ),
            "observed_at": request["as_of"].isoformat(),
        }

    def _resolve_fx(
        self,
        *,
        request: Mapping[str, Any],
        candidate: Mapping[str, Any],
        functional_currency: str,
        recognition_date: date,
    ) -> dict[str, Any]:
        transaction_currency = str(candidate["transaction_currency"])
        if transaction_currency == functional_currency:
            return {
                "mode": "SAME_CURRENCY",
                "base_currency": transaction_currency,
                "quote_currency": functional_currency,
                "normalized_rate": "1",
                "desired_rate_date": recognition_date.isoformat(),
                "selected_rate_date": recognition_date.isoformat(),
                "staleness_business_days": 0,
                "snapshot_hash": None,
                "policy_hash": None,
            }
        resolved = self._fx_rates.resolve_rate(
            tenant_id=request["tenant_id"],
            company_id=str(candidate["company_id"]),
            purpose="TRANSACTION_SPOT",
            base_currency=transaction_currency,
            quote_currency=functional_currency,
            desired_rate_date=recognition_date,
            as_of=request["as_of"],
        )
        return {
            "mode": "APPROVED_SNAPSHOT",
            "base_currency": transaction_currency,
            "quote_currency": functional_currency,
            "normalized_rate": str(resolved["normalized_rate"]),
            "desired_rate_date": str(resolved["desired_rate_date"]),
            "selected_rate_date": str(resolved["selected_rate_date"]),
            "staleness_business_days": int(resolved["staleness_business_days"]),
            "snapshot_hash": str(resolved["snapshot_hash"]),
            "policy_hash": str(resolved["policy_hash"]),
        }


def _request(candidate_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "tenant_id",
        "expected_revision_no",
        "expected_candidate_hash",
        "as_of",
    }
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise _invalid("Unsupported fields: " + ", ".join(unknown))
    if payload.get("schema_version") != "eos_voucher_candidate_validate.v1":
        raise _invalid("schema_version must be eos_voucher_candidate_validate.v1")
    tenant_id = str(payload.get("tenant_id", "")).strip()
    if not tenant_id or len(tenant_id) > 128:
        raise _invalid("tenant_id must be a non-empty scoped identifier")
    try:
        candidate_id = str(uuid.UUID(str(candidate_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid("candidate_id must be a UUID") from exc
    revision_no = payload.get("expected_revision_no")
    if (
        isinstance(revision_no, bool)
        or not isinstance(revision_no, int)
        or revision_no < 1
    ):
        raise _invalid("expected_revision_no must be a positive integer")
    try:
        candidate_hash = validate_hash_ref(
            str(payload.get("expected_candidate_hash", ""))
        )
    except ValueError as exc:
        raise _invalid(str(exc)) from exc
    raw_as_of = payload.get("as_of")
    try:
        as_of = datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _invalid("as_of must be an ISO 8601 date-time") from exc
    if as_of.tzinfo is None:
        raise _invalid("as_of must include a timezone")
    return {
        "tenant_id": tenant_id,
        "candidate_id": candidate_id,
        "expected_revision_no": revision_no,
        "expected_candidate_hash": candidate_hash,
        "as_of": as_of.astimezone(UTC),
    }


def _require_current_candidate(
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    revision: Mapping[str, Any],
) -> None:
    if candidate["state"] not in _ALLOWED_CANDIDATE_STATES:
        raise _rejected(
            "EOS_CANDIDATE_STATE_NOT_VALIDATABLE",
            "VoucherCandidate state is not eligible for validation.",
        )
    if (
        candidate["current_revision_no"] != request["expected_revision_no"]
        or revision["revision_no"] != request["expected_revision_no"]
        or revision["candidate_hash"] != request["expected_candidate_hash"]
    ):
        raise EosCandidateValidationError(
            "EOS_CANDIDATE_REVISION_CONFLICT",
            "VoucherCandidate revision or semantic hash changed before validation.",
            status_code=409,
        )


def _require_accounts(
    candidate: Mapping[str, Any], catalog: Mapping[str, Any]
) -> list[dict[str, Any]]:
    by_id = {str(row["account_id"]): row for row in catalog["accounts"]}
    transaction_currency = str(candidate["transaction_currency"])
    policies: dict[str, dict[str, Any]] = {}
    for line in candidate["lines"]:
        account_id = str(line["account_id"])
        policy = by_id.get(account_id)
        if policy is None:
            raise _rejected(
                "EOS_CANDIDATE_ACCOUNT_UNAVAILABLE",
                f"Account {account_id} has no effective approved policy.",
            )
        if not policy["is_postable_leaf"]:
            raise _rejected(
                "EOS_CANDIDATE_ACCOUNT_NOT_POSTABLE",
                f"Account {account_id} is not an approved postable leaf.",
            )
        if transaction_currency not in tuple(policy["allowed_currencies"]):
            raise _rejected(
                "EOS_CANDIDATE_ACCOUNT_CURRENCY_DENIED",
                f"Account {account_id} does not admit {transaction_currency}.",
            )
        policies[str(policy["policy_id"])] = {
            "policy_id": str(policy["policy_id"]),
            "account_id": account_id,
            "catalog_release_id": str(policy["catalog_release_id"]),
            "posting_rule_id": str(policy["posting_rule_id"]),
            "rule_revision": int(policy["rule_revision"]),
            "approved_proof_ref": str(policy["approved_proof_ref"]),
            "allowed_currencies": sorted(
                str(value) for value in policy["allowed_currencies"]
            ),
        }
    return [policies[key] for key in sorted(policies)]


def _stored_date(field: str, value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be an ISO date") from exc


def _invalid(detail: str) -> EosCandidateValidationError:
    return EosCandidateValidationError(
        "EOS_CANDIDATE_VALIDATION_INVALID", detail, status_code=422
    )


def _rejected(error_code: str, detail: str) -> EosCandidateValidationError:
    return EosCandidateValidationError(error_code, detail, status_code=409)
