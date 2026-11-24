from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from mybee_ax.orchestration import M1PreparationAuthority, M1PreparationRegistration
from nex_runtime.business_context import (
    BusinessContextValidationError,
    validate_business_request_context,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from .m1_product_preparation_coordinator import M1ProductPreparationCoordinatorError
from .planning_capabilities import (
    CapabilitySnapshotError,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)
from .product_planning_coordinators import ProductPlanningCoordinatorRegistration

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
M1_PREPARATION_AUTHORITY_SOURCE_IDENTITY = (
    "nex-ae:m1-preparation-authority:http-eos-oa:v1"
)

_RESPONSE_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "request_hash",
        "authority",
        "accounting_period",
        "resolution_hash",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "requester_subject_id",
        "company_id",
        "company_code",
        "company_selector_kind",
        "company_selector_value",
        "company_version",
        "company_evidence_hash",
        "functional_currency",
        "primary_project_id",
        "primary_project_code",
        "project_refs",
        "project_authorizations",
        "debit_account_id",
        "debit_semantic_key",
        "debit_account_evidence_hash",
        "credit_account_id",
        "credit_semantic_key",
        "credit_account_evidence_hash",
        "business_approval_policy_id",
        "business_approval_policy_version",
        "business_approval_policy_hash",
        "accounting_approval_policy_id",
        "accounting_approval_policy_version",
        "accounting_approval_policy_hash",
        "project_authorization_ref",
        "project_authorization_revision_hash",
        "authority_effective_at",
        "authority_hash",
    }
)
_PERIOD_FIELDS = frozenset(
    {
        "period_id",
        "fiscal_year",
        "period_no",
        "state",
        "version",
        "start_date",
        "end_date",
        "evidence_hash",
    }
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


class HttpM1PreparationAuthoritySource:
    """Strict installed AE consumer for owner-authoritative EOS resolution."""

    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        coordinator_registration: ProductPlanningCoordinatorRegistration,
        preparation_registration: M1PreparationRegistration,
        timeout_seconds: float = 15.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid("EOS authority base URL must use HTTP(S).")
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid("EOS authority service token is required.")
        if timeout_seconds <= 0:
            raise _invalid("EOS authority timeout must be positive.")
        if (
            coordinator_registration.preparation_adapter_source_identity
            != preparation_registration.source_identity
        ):
            raise _invalid("Coordinator and preparation authority releases differ.")
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._token = service_token.strip()
        self._coordinator = coordinator_registration
        self._preparation = preparation_registration
        self._timeout = float(timeout_seconds)
        self._opener = opener

    def resolve(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
        checkpoint: Mapping[str, Any] | None,
    ) -> M1PreparationAuthority:
        del checkpoint
        request_body = self.build_request(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        outgoing = Request(
            urljoin(self._base_url, TRANSACTION_PREPARATION_AUTHORITY_PATH.lstrip("/")),
            data=json.dumps(
                request_body, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-NeX-Tenant-Id": request_body["tenant_id"],
                "X-NeX-Subject-Id": request_body["requester_subject_id"],
                "X-NeX-Correlation-Id": request_body["correlation_id"],
            },
        )
        try:
            with self._opener(outgoing, timeout=self._timeout) as response:
                payload = _json_object(response.read())
        except HTTPError as exc:
            problem = _optional_json_object(exc.read())
            raise M1ProductPreparationCoordinatorError(
                str(
                    problem.get(
                        "error_code",
                        "M1_PREPARATION_AUTHORITY_REJECTED",
                    )
                ),
                "EOS rejected transaction preparation authority resolution.",
                retryable=bool(problem.get("retryable", exc.code >= 500)),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise _unavailable("EOS transaction preparation authority is unavailable.") from exc
        return admit_transaction_preparation_authority(
            payload,
            request=request_body,
            preparation_registration=self._preparation,
        )

    def build_request(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            context = validate_business_request_context(
                work_intent.get("business_request_context")
            )
            snapshot = validate_capability_snapshot_contract(capability_snapshot)
            capability_by_exact_version(
                snapshot,
                self._coordinator.capability_id,
                self._coordinator.capability_version,
            )
        except (BusinessContextValidationError, CapabilitySnapshotError) as exc:
            raise _invalid("M1 authority input contracts are not admitted.") from exc
        identity = agent_context.get("identity")
        if not isinstance(identity, Mapping):
            raise _invalid("AgentContext identity is unavailable.")
        tenant_id = _scoped_id("tenant_id", identity.get("tenant_id"))
        subject_id = _scoped_id(
            "requester_subject_id",
            identity.get("subject_id") or identity.get("principal_id"),
        )
        execution_id = _scoped_id("execution_id", work_intent.get("execution_id"))
        if (
            snapshot["tenant_id"] != tenant_id
            or agent_context.get("execution_id") != execution_id
            or execution.get("execution_id") != execution_id
            or work_intent.get("business_context_hash") != context["context_hash"]
        ):
            raise _conflict("M1 authority request lineage differs.")
        transaction = context["transaction"]
        project_codes = [
            item["project_code"] for item in context["requested_allocation"]
        ]
        if not project_codes:
            project_codes = [_primary_project_code(work_intent)]
        body = {
            "schema_version": TRANSACTION_PREPARATION_AUTHORITY_REQUEST_SCHEMA,
            "tenant_id": tenant_id,
            "requester_subject_id": subject_id,
            "business_context_hash": context["context_hash"],
            "company_selector": dict(context["company_selector"]),
            "project_codes": project_codes,
            "amount": transaction["amount"],
            "currency": transaction["currency"],
            "recognition_date": transaction["recognition_date"],
            "debit_semantic_key": self._preparation.debit_semantic_key,
            "credit_semantic_key": self._preparation.credit_semantic_key,
            "capability_binding": self._coordinator.trigger_capability.projection(),
            "coordinator_binding": {
                "coordinator_id": self._coordinator.coordinator_id,
                "coordinator_version": self._coordinator.coordinator_version,
                "coordinator_registration_hash": self._coordinator.registration_hash,
                "preparation_adapter_source_identity": (
                    self._coordinator.preparation_adapter_source_identity
                ),
            },
            "correlation_id": execution_id,
        }
        body["request_hash"] = semantic_sha256_hash_ref(
            {
                "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-REQUEST-V1",
                **body,
            }
        )
        return body


def _primary_project_code(work_intent: Mapping[str, Any]) -> str:
    parameters = work_intent.get("parameter_candidates")
    matches = [
        str(item.get("value") or "").strip().upper()
        for item in parameters
        if isinstance(item, Mapping) and item.get("name") == "primary_project_code"
    ] if isinstance(parameters, list) else []
    if len(matches) != 1 or not matches[0]:
        raise _invalid("Primary Project Code is unavailable.")
    return matches[0]


def admit_transaction_preparation_authority(
    value: object,
    *,
    request: Mapping[str, Any],
    preparation_registration: M1PreparationRegistration,
) -> M1PreparationAuthority:
    response = _exact("response", value, _RESPONSE_FIELDS)
    if (
        response["schema_version"]
        != TRANSACTION_PREPARATION_AUTHORITY_RESPONSE_SCHEMA
        or response["operation"] != TRANSACTION_PREPARATION_AUTHORITY_OPERATION
        or response["request_hash"] != request["request_hash"]
    ):
        raise _drift("EOS authority response identity drifted.")
    expected_resolution = semantic_sha256_hash_ref(
        {
            "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-RESOLUTION-V1",
            **{
                key: item
                for key, item in response.items()
                if key != "resolution_hash"
            },
        }
    )
    if response["resolution_hash"] != expected_resolution:
        raise _drift("EOS authority resolution hash drifted.")
    authority = _exact("authority", response["authority"], _AUTHORITY_FIELDS)
    expected_authority = semantic_sha256_hash_ref(
        {key: item for key, item in authority.items() if key != "authority_hash"}
    )
    if authority["authority_hash"] != expected_authority:
        raise _drift("EOS authority hash drifted.")
    if (
        authority["schema_version"] != "nex.mybee.m1-preparation-authority.v1"
        or authority["tenant_id"] != request["tenant_id"]
        or authority["requester_subject_id"] != request["requester_subject_id"]
        or authority["company_selector_kind"]
        != request["company_selector"]["kind"]
        or authority["company_selector_value"]
        != request["company_selector"]["value"]
        or authority["debit_semantic_key"] != request["debit_semantic_key"]
        or authority["credit_semantic_key"] != request["credit_semantic_key"]
        or authority["debit_semantic_key"]
        != preparation_registration.debit_semantic_key
        or authority["credit_semantic_key"]
        != preparation_registration.credit_semantic_key
    ):
        raise _drift("EOS authority content binding drifted.")
    project_refs = authority["project_refs"]
    project_authorizations = authority["project_authorizations"]
    if (
        not isinstance(project_refs, list)
        or not isinstance(project_authorizations, list)
        or [item.get("project_code") for item in project_refs]
        != request["project_codes"]
        or [item.get("project_code") for item in project_authorizations]
        != request["project_codes"]
    ):
        raise _drift("EOS Project authority set drifted.")
    for name in (
        "company_evidence_hash",
        "debit_account_evidence_hash",
        "credit_account_evidence_hash",
        "business_approval_policy_hash",
        "accounting_approval_policy_hash",
        "project_authorization_revision_hash",
    ):
        _hash(name, authority[name])
    period = _exact("accounting_period", response["accounting_period"], _PERIOD_FIELDS)
    if period["state"] != "OPEN":
        raise _drift("EOS AccountingPeriod is not OPEN.")
    expected_period = semantic_sha256_hash_ref(
        {
            "domain": "EOS-ACCOUNTING-PERIOD-AUTHORITY-V1",
            **{key: item for key, item in period.items() if key != "evidence_hash"},
        }
    )
    if period["evidence_hash"] != expected_period:
        raise _drift("EOS AccountingPeriod evidence hash drifted.")
    recognized = date.fromisoformat(str(request["recognition_date"]))
    if not (
        date.fromisoformat(str(period["start_date"]))
        <= recognized
        <= date.fromisoformat(str(period["end_date"]))
    ):
        raise _drift("EOS AccountingPeriod does not cover recognition date.")
    try:
        effective_at = datetime.fromisoformat(
            str(authority["authority_effective_at"]).replace("Z", "+00:00")
        )
        if effective_at.tzinfo is None:
            raise ValueError("timezone missing")
        converted = M1PreparationAuthority(
            **{
                key: item
                for key, item in authority.items()
                if key
                not in {
                    "schema_version",
                    "authority_hash",
                    "project_refs",
                    "project_authorizations",
                    "authority_effective_at",
                }
            },
            project_refs=tuple(dict(item) for item in project_refs),
            project_authorizations=tuple(
                dict(item) for item in project_authorizations
            ),
            authority_effective_at=effective_at.astimezone(UTC),
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise _drift("EOS authority projection is malformed.") from exc
    return converted


def _exact(name: str, value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _drift(f"EOS {name} fields drifted.")
    return dict(value)


def _json_object(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _drift("EOS authority response is not JSON.") from exc
    if not isinstance(value, Mapping):
        raise _drift("EOS authority response is not an object.")
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
        raise _invalid(f"{name} is invalid.")
    return text


def _hash(name: str, value: object) -> str:
    try:
        return validate_hash_ref(str(value))
    except ValueError as exc:
        raise _drift(f"EOS {name} is invalid.") from exc


def _invalid(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "M1_PREPARATION_AUTHORITY_REQUEST_INVALID", detail
    )


def _conflict(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "M1_PREPARATION_AUTHORITY_CONFLICT", detail
    )


def _drift(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "M1_PREPARATION_AUTHORITY_RESPONSE_DRIFT", detail
    )


def _unavailable(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "M1_PREPARATION_AUTHORITY_UNAVAILABLE", detail, retryable=True
    )


__all__ = [
    "TRANSACTION_PREPARATION_AUTHORITY_OPERATION",
    "TRANSACTION_PREPARATION_AUTHORITY_PATH",
    "HttpM1PreparationAuthoritySource",
    "admit_transaction_preparation_authority",
]
