"""Approved COA and FX policy inputs sent only through canonical EOS APIs."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import (
    canonical_json,
    eos_fx_policy_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from ..domain.coa_approval import (
    CoaApprovalAdmission,
    CoaApprovalAdmissionError,
    text_file_sha256_hash_ref,
    validate_product_accounting_admission,
)
from ..domain.coa_candidate import CoaCandidateError, load_json_object

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_FX_SCHEMA = "nex.mybee.fx.approved-rate-source-policy.v1"
_FX_STATUS = "PRODUCT_FINANCE_APPROVED_SOURCE_POLICY"
_FX_PROFILE = "mybee.finance.fx.smbs-market-base-manual"
_COA_PUBLISH_ENDPOINT = "/internal/v2/finance/coa/releases/{release_id}/publish"


class FinanceInputBundleError(ValueError):
    """Raised when immutable finance input evidence or runtime binding drifts."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class FinanceInputApiError(RuntimeError):
    """Redacted canonical EOS transport failure."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class EosApiRequest:
    method: str
    path: str
    tenant_id: str
    subject_id: str
    payload: Mapping[str, Any]


class EosFinanceInputTransport(Protocol):
    def send(self, request: EosApiRequest) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ApprovedFinanceInputBundle:
    coa_manifest: Mapping[str, Any]
    coa_admission: CoaApprovalAdmission
    fx_policy: Mapping[str, Any]
    bundle_hash: str

    def coa_publication_request(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        definition_release_id: str,
        business_operation_id: str,
        idempotency_key: str,
    ) -> EosApiRequest:
        release_id = _uuid("definition_release_id", definition_release_id)
        payload = {
            "business_operation_id": _uuid(
                "business_operation_id", business_operation_id
            ),
            "idempotency_key": _text("idempotency_key", idempotency_key, maximum=256),
            "source_reference": self.coa_manifest["source_reference"],
            "source_hash": self.coa_manifest["source_hash"],
            "approved_proof_ref": self.coa_manifest["approved_proof_hash"],
            "content_hash": self.coa_manifest["node_contract_hash"],
        }
        return EosApiRequest(
            method="POST",
            path=_COA_PUBLISH_ENDPOINT.format(release_id=release_id),
            tenant_id=_scoped_id("tenant_id", tenant_id),
            subject_id=_scoped_id("subject_id", subject_id),
            payload=payload,
        )

    def fx_policy_request(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        company_id: str,
        policy_id: str,
        effective_from: date,
        approved_by: str,
        approval_proof_hash: str,
        base_currency: str = "USD",
        quote_currency: str = "KRW",
        version: int = 1,
        effective_to: date | None = None,
    ) -> EosApiRequest:
        pair = {
            "base_currency": _currency("base_currency", base_currency),
            "quote_currency": _currency("quote_currency", quote_currency),
        }
        if pair not in self.fx_policy["phase1_supported_pairs"]:
            raise FinanceInputBundleError(
                "FX_PAIR_NOT_ADMITTED", f"{base_currency}/{quote_currency}"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise FinanceInputBundleError(
                "FX_EFFECTIVE_PERIOD_INVALID", "effective_to must follow effective_from"
            )
        if type(version) is not int or version < 1:
            raise FinanceInputBundleError(
                "FX_VERSION_INVALID", "positive integer required"
            )

        defaults = self.fx_policy["eos_policy_defaults"]
        semantics = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "company_id": _uuid("company_id", company_id),
            "policy_id": _uuid("policy_id", policy_id),
            "version": version,
            **pair,
            "purpose": defaults["purpose"],
            "rate_kind": defaults["rate_kind"],
            "source_provider_id": self.fx_policy["source"]["provider_id"],
            "publication_selector": defaults["publication_selector"],
            "effective_from": _date("effective_from", effective_from),
            "effective_to": (
                _date("effective_to", effective_to)
                if effective_to is not None
                else None
            ),
            "allow_previous_business_day": defaults["allow_previous_business_day"],
            "max_staleness_business_days": defaults["max_staleness_business_days"],
            "rounding_mode": defaults["rounding_mode"],
            "rate_decimal_scale": defaults["rate_decimal_scale"],
            "approved_by": _scoped_id("approved_by", approved_by),
            "approval_proof_hash": _hash_ref(
                "approval_proof_hash", approval_proof_hash
            ),
        }
        payload = {key: value for key, value in semantics.items() if key != "tenant_id"}
        payload["policy_hash"] = eos_fx_policy_hash_ref(semantics)
        return EosApiRequest(
            method="POST",
            path=self.fx_policy["runtime_boundaries"]["policy_endpoint"],
            tenant_id=semantics["tenant_id"],
            subject_id=_scoped_id("subject_id", subject_id),
            payload=payload,
        )


class EosFinanceInputClient:
    def __init__(self, transport: EosFinanceInputTransport) -> None:
        self._transport = transport

    def publish_coa(
        self, bundle: ApprovedFinanceInputBundle, **runtime_bindings: Any
    ) -> Mapping[str, Any]:
        return self._transport.send(bundle.coa_publication_request(**runtime_bindings))

    def create_fx_policy(
        self, bundle: ApprovedFinanceInputBundle, **runtime_bindings: Any
    ) -> Mapping[str, Any]:
        return self._transport.send(bundle.fx_policy_request(**runtime_bindings))


class HttpEosFinanceInputTransport:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise FinanceInputBundleError(
                "EOS_BASE_URL_INVALID", "http(s) URL required"
            )
        if not service_token.strip():
            raise FinanceInputBundleError(
                "EOS_SERVICE_TOKEN_MISSING", "service token is required"
            )
        if timeout_seconds <= 0:
            raise FinanceInputBundleError(
                "EOS_TIMEOUT_INVALID", "timeout must be positive"
            )
        self._base_url = base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: EosApiRequest) -> Mapping[str, Any]:
        body = canonical_json(dict(request.payload)).encode("utf-8")
        outgoing = Request(
            urljoin(self._base_url, request.path.lstrip("/")),
            data=body,
            method=request.method,
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "X-NeX-Tenant-Id": request.tenant_id,
                "X-NeX-Subject-Id": request.subject_id,
            },
        )
        try:
            with urlopen(outgoing, timeout=self._timeout_seconds) as response:
                return _json_object(response.read())
        except HTTPError as error:
            problem = _optional_json_object(error.read())
            raise FinanceInputApiError(
                str(problem.get("error_code", "EOS_FINANCE_INPUT_REJECTED")),
                "EOS rejected the approved finance input",
                status_code=error.code,
                retryable=bool(problem.get("retryable", error.code >= 500)),
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise FinanceInputApiError(
                "EOS_FINANCE_INPUT_UNAVAILABLE",
                "EOS finance input endpoint is unavailable",
                status_code=503,
                retryable=True,
            ) from error


def load_approved_finance_input_bundle(root: Path) -> ApprovedFinanceInputBundle:
    root = root.resolve()
    account_config = root / "domains/mybee/config/account_catalog"
    candidate_path = (
        root / "docs/transition/MyBee_Phase1/NeX_MyBee_COA_Codebook_Candidate_v0.1.json"
    )
    try:
        candidate = load_json_object(candidate_path)
        identity = load_json_object(
            account_config / "unified_codebook_candidate.identity.v1.json"
        )
        approval = load_json_object(
            account_config / "product_accounting_approval.v1.json"
        )
        approved_source = load_json_object(
            account_config / "approved_standard_chart.v1.json"
        )
        coa_manifest = load_json_object(account_config / "approved_seed_manifest.json")
        admission = validate_product_accounting_admission(
            candidate=candidate,
            candidate_file_hash=text_file_sha256_hash_ref(candidate_path),
            candidate_identity=identity,
            approval=approval,
            approved_source=approved_source,
            seed_manifest=coa_manifest,
        )
        fx_policy = load_json_object(
            root / "domains/mybee/config/fx/approved_rate_source_policy.json"
        )
    except (CoaCandidateError, CoaApprovalAdmissionError) as error:
        raise FinanceInputBundleError("COA_INPUT_NOT_ADMITTED", str(error)) from error
    validate_approved_fx_source_policy(fx_policy)
    bundle_hash = semantic_sha256_hash_ref(
        {
            "schema_version": "nex.mybee.finance-input-bundle.v1",
            "coa_manifest": coa_manifest,
            "fx_policy": fx_policy,
        }
    )
    return ApprovedFinanceInputBundle(
        coa_manifest=dict(coa_manifest),
        coa_admission=admission,
        fx_policy=dict(fx_policy),
        bundle_hash=bundle_hash,
    )


def validate_approved_fx_source_policy(value: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "policy_profile_id",
        "policy_profile_version",
        "status",
        "approved_on",
        "approval",
        "source",
        "phase1_supported_pairs",
        "eos_policy_defaults",
        "required_runtime_bindings",
        "source_snapshot_requirements",
        "runtime_boundaries",
        "deferred_automation",
        "policy_contract_hash",
    }
    if set(value) != expected_keys:
        raise FinanceInputBundleError("FX_POLICY_FIELDS_INVALID", "root fields drifted")
    expected_identity = (_FX_SCHEMA, _FX_PROFILE, 1, _FX_STATUS)
    actual_identity = tuple(
        value.get(field)
        for field in (
            "schema_version",
            "policy_profile_id",
            "policy_profile_version",
            "status",
        )
    )
    if actual_identity != expected_identity:
        raise FinanceInputBundleError("FX_POLICY_IDENTITY_INVALID", "identity drifted")
    source = value.get("source")
    if not isinstance(source, Mapping):
        raise FinanceInputBundleError("FX_SOURCE_INVALID", "object required")
    if (
        source.get("automatic_fetch_enabled") is not False
        or source.get("rate_values_included") is not False
        or source.get("legal_rate_claim") != "NONE"
        or source.get("acquisition_mode") != "MANUAL_APPROVED_IMPORT"
    ):
        raise FinanceInputBundleError(
            "FX_SOURCE_BOUNDARY_INVALID", "policy must not contain or fetch rate values"
        )
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "policy_contract_hash"}
    )
    if value.get("policy_contract_hash") != expected_hash:
        raise FinanceInputBundleError("FX_POLICY_HASH_MISMATCH", "policy drifted")


def _json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FinanceInputApiError(
            "EOS_FINANCE_INPUT_RESPONSE_INVALID",
            "EOS returned a non-JSON response",
            status_code=502,
            retryable=True,
        ) from error
    if not isinstance(value, dict):
        raise FinanceInputApiError(
            "EOS_FINANCE_INPUT_RESPONSE_INVALID",
            "EOS returned a non-object response",
            status_code=502,
            retryable=True,
        )
    return value


def _optional_json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise FinanceInputBundleError(
            f"{field.upper()}_INVALID", "UUID required"
        ) from error


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise FinanceInputBundleError(
            f"{field.upper()}_INVALID", "stable scoped identifier required"
        )
    return normalized


def _currency(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _CURRENCY.fullmatch(normalized) is None:
        raise FinanceInputBundleError(
            f"{field.upper()}_INVALID", "ISO 4217 code required"
        )
    return normalized


def _date(field: str, value: object) -> str:
    if not isinstance(value, date):
        raise FinanceInputBundleError(f"{field.upper()}_INVALID", "date required")
    return value.isoformat()


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as error:
        raise FinanceInputBundleError(
            f"{field.upper()}_INVALID", "SHA-256 hash reference required"
        ) from error


def _text(field: str, value: object, *, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise FinanceInputBundleError(
            f"{field.upper()}_INVALID", f"1..{maximum} characters required"
        )
    return normalized
