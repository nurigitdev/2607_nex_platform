"""D12 Project template and canonical EOS consumer contract."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from .work_codes import (
    CATALOG_ID,
    MANDATORY_D12_WORK_CODE_IDS,
    WorkCodeCatalog,
    load_work_code_catalog,
)

TEMPLATE_SCHEMA_VERSION = "nex.mybee.d12-project-template.v1"
TEMPLATE_ID = "mybee.d12.required-five"
TEMPLATE_VERSION = "1.0.0"
TEMPLATE_STATUS = "EOS_CONSUMER_ADMITTED"
TEMPLATE_DIGEST = (
    "sha256:5476e505e33ceb2551f8edb080010b34e5425906029df3c90214751177274fe3"
)
MANDATORY_CODES_HASH = (
    "sha256:f867477ed5983904e1c4a353bf05a4a11ffb56b5fa0299ffd63bbc8cd70bd9a1"
)
PROVIDER_LOCK_REF = "domains/mybee/compatibility/platform.lock.json#/openapi/nex-eos"

APPROVE_OPERATION = "PROJECT.WORK_CODE_SET.APPROVE"
GET_OPERATION = "PROJECT.WORK_CODE_SET.GET"
READINESS_OPERATION = "PROJECT.BUSINESS_READINESS.GET"

DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "templates/d12/required_five.json"
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "template_id",
        "template_version",
        "revision",
        "status",
        "catalog_binding",
        "eos_consumer_contract",
        "readiness_contract",
        "runtime_boundaries",
        "release_attestation",
    }
)
_REQUIRED_TRUE_FLAGS = (
    "required_codes_ok",
    "project_company_bound",
    "pm_assigned",
    "members_eligible",
    "pa_identity_bound",
    "budget_bound_if_required",
)
_EXPECTED_ENDPOINTS = {
    "approve": {
        "method": "POST",
        "path_template": ("/internal/v2/projects/{project_id}/work-code-sets:approve"),
        "operation_id": APPROVE_OPERATION,
        "business_scope": "project:work-code:approve",
        "route_class": "WRITE",
    },
    "current_work_set": {
        "method": "GET",
        "path_template": "/internal/v2/projects/{project_id}/work-code-set",
        "operation_id": GET_OPERATION,
        "business_scope": "project:work-code:read",
        "side_effect_free": True,
    },
    "business_readiness": {
        "method": "GET",
        "path_template": "/internal/v2/projects/{project_id}/business-readiness",
        "operation_id": READINESS_OPERATION,
        "business_scope": "project:work-code:read",
        "side_effect_free": True,
    },
}
_EXPECTED_READINESS = {
    "technical_project_status": "ACTIVE",
    "required_projection_state": "BUSINESS_READY",
    "required_true_flags": list(_REQUIRED_TRUE_FLAGS),
    "active_is_not_business_ready": True,
    "pa_domain_write_requires_business_ready": True,
}
_EXPECTED_BOUNDARIES = {
    "direct_database_access": False,
    "service_private_imports": False,
    "nsl_tool_binding_status": "DEFERRED_TO_MB8_01",
    "work_assignment_status": "DEFERRED_TO_S1_06",
}


class ProjectTemplateError(ValueError):
    """Raised when a D12 template or EOS projection fails closed."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class EosProjectTemplateRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    subject_id: str
    payload: Mapping[str, Any] | None = None
    query: Mapping[str, str] | None = None


class EosProjectTemplateTransport(Protocol):
    def send(self, request: EosProjectTemplateRequest) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class D12ProjectBusinessReadiness:
    tenant_id: str
    project_id: str
    effective_on: date
    work_set_hash: str
    company_binding_ids: tuple[str, ...]
    source_hash: str
    work_set: Mapping[str, Any]


@dataclass(frozen=True)
class D12ProjectTemplate:
    template_id: str
    template_version: str
    revision: int
    status: str
    catalog_id: str
    catalog_version: str
    catalog_digest: str
    mandatory_codes_hash: str
    required_code_ids: tuple[str, ...]
    template_digest: str

    def approval_request(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        business_operation_id: str,
        idempotency_key: str,
        work_set_id: str,
        revision: int,
        approved_proof_hash: str,
        pm_subject_id: str,
        pa_agent_id: str,
        pa_identity_evidence_hash: str,
        effective_from: date,
    ) -> EosProjectTemplateRequest:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        subject_id = _scoped_id("subject_id", subject_id)
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "business_operation_id": _uuid(
                "business_operation_id", business_operation_id
            ),
            "idempotency_key": _text("idempotency_key", idempotency_key, maximum=256),
            "requester_subject_id": subject_id,
            "requested_operation": APPROVE_OPERATION,
            "work_set": {
                "work_set_id": _uuid("work_set_id", work_set_id),
                "revision": _positive_int("revision", revision),
                "catalog_id": self.catalog_id,
                "catalog_version": self.catalog_version,
                "catalog_digest": self.catalog_digest,
                "template_ref": self.template_id,
                "template_version": self.template_version,
                "code_ids": list(self.required_code_ids),
                "approved_proof_hash": _hash_ref(
                    "approved_proof_hash", approved_proof_hash
                ),
                "pm_subject_id": _scoped_id("pm_subject_id", pm_subject_id),
                "pa_agent_id": _scoped_id("pa_agent_id", pa_agent_id),
                "pa_identity_evidence_hash": _hash_ref(
                    "pa_identity_evidence_hash", pa_identity_evidence_hash
                ),
                "effective_from": _date("effective_from", effective_from).isoformat(),
            },
        }
        if payload["work_set"]["pm_subject_id"] == payload["work_set"]["pa_agent_id"]:
            raise ProjectTemplateError(
                "PROJECT_ACTOR_CONFLICT", "human PM and PA identity must differ"
            )
        payload["payload_hash"] = d12_project_work_set_payload_hash(
            {**payload, "project_id": project_id}
        )
        return EosProjectTemplateRequest(
            method="POST",
            path=_EXPECTED_ENDPOINTS["approve"]["path_template"].format(
                project_id=project_id
            ),
            operation_id=APPROVE_OPERATION,
            tenant_id=tenant_id,
            subject_id=subject_id,
            payload=MappingProxyType(payload),
        )

    def current_work_set_request(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        effective_on: date | None = None,
    ) -> EosProjectTemplateRequest:
        return self._read_request(
            endpoint="current_work_set",
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=subject_id,
            effective_on=effective_on,
        )

    def business_readiness_request(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        effective_on: date | None = None,
    ) -> EosProjectTemplateRequest:
        return self._read_request(
            endpoint="business_readiness",
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=subject_id,
            effective_on=effective_on,
        )

    def admit_work_set(
        self,
        value: object,
        *,
        tenant_id: str,
        project_id: str,
    ) -> Mapping[str, Any]:
        item = _object(value, code="EOS_WORK_SET_INVALID")
        expected_tenant = _scoped_id("tenant_id", tenant_id)
        expected_project = _uuid("project_id", project_id)
        if (
            item.get("tenant_id") != expected_tenant
            or item.get("project_id") != expected_project
        ):
            raise ProjectTemplateError(
                "EOS_WORK_SET_SCOPE_MISMATCH", "tenant or Project identity drifted"
            )
        expected_identity = (
            self.catalog_id,
            self.catalog_version,
            self.catalog_digest,
            self.mandatory_codes_hash,
            self.template_id,
            self.template_version,
            "APPROVED",
        )
        actual_identity = tuple(
            item.get(field)
            for field in (
                "catalog_id",
                "catalog_version",
                "catalog_digest",
                "mandatory_codes_hash",
                "template_ref",
                "template_version",
                "state",
            )
        )
        if actual_identity != expected_identity:
            raise ProjectTemplateError(
                "EOS_WORK_SET_IDENTITY_MISMATCH", "catalog or template identity drifted"
            )
        code_ids = _string_sequence("code_ids", item.get("code_ids"))
        if code_ids != self.required_code_ids:
            raise ProjectTemplateError(
                "EOS_WORK_SET_CODES_MISMATCH", "required D12 code set drifted"
            )
        _positive_int("revision", item.get("revision"))
        _uuid("work_set_id", item.get("work_set_id"))
        _hash_ref("work_set_hash", item.get("work_set_hash"))
        _hash_ref("approved_proof_hash", item.get("approved_proof_hash"))
        _hash_ref("pa_identity_evidence_hash", item.get("pa_identity_evidence_hash"))
        _date_text("effective_from", item.get("effective_from"))
        return MappingProxyType(dict(item))

    def require_business_ready(
        self,
        value: object,
        *,
        tenant_id: str,
        project_id: str,
    ) -> D12ProjectBusinessReadiness:
        item = _object(value, code="EOS_BUSINESS_READINESS_INVALID")
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        if item.get("tenant_id") != tenant_id or item.get("project_id") != project_id:
            raise ProjectTemplateError(
                "EOS_READINESS_SCOPE_MISMATCH", "tenant or Project identity drifted"
            )
        reason_codes = _string_sequence("reason_codes", item.get("reason_codes"))
        effective_on = _date_text("effective_on", item.get("effective_on"))
        raw_work_set_hash = item.get("work_set_hash")
        work_set_hash = (
            _hash_ref("work_set_hash", raw_work_set_hash)
            if raw_work_set_hash is not None
            else None
        )
        company_binding_ids = tuple(
            _uuid("company_binding_id", value)
            for value in _string_sequence(
                "company_binding_ids", item.get("company_binding_ids")
            )
        )
        if company_binding_ids != tuple(sorted(company_binding_ids)):
            raise ProjectTemplateError(
                "EOS_READINESS_BINDINGS_INVALID", "company bindings must be ordered"
            )
        source = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "technical_status": item.get("technical_status"),
            "work_set_hash": work_set_hash,
            "company_binding_ids": list(company_binding_ids),
            "required_codes_ok": item.get("required_codes_ok"),
            "project_company_bound": item.get("project_company_bound"),
            "pm_assigned": item.get("pm_assigned"),
            "members_eligible": item.get("members_eligible"),
            "pa_identity_bound": item.get("pa_identity_bound"),
            "effective_on": effective_on.isoformat(),
        }
        expected_source_hash = semantic_sha256_hash_ref(
            {"domain": "EOS-PROJECT-BUSINESS-READINESS-V1", **source}
        )
        if item.get("source_hash") != expected_source_hash:
            raise ProjectTemplateError(
                "EOS_READINESS_HASH_MISMATCH", "readiness source hash drifted"
            )
        ready = (
            item.get("technical_status") == "ACTIVE"
            and item.get("state") == "BUSINESS_READY"
            and item.get("business_ready") is True
            and work_set_hash is not None
            and all(item.get(flag) is True for flag in _REQUIRED_TRUE_FLAGS)
            and not reason_codes
        )
        if not ready:
            detail = ",".join(reason_codes) if reason_codes else "projection mismatch"
            raise ProjectTemplateError("PROJECT_NOT_BUSINESS_READY", detail)
        work_set = self.admit_work_set(
            item.get("work_set"), tenant_id=tenant_id, project_id=project_id
        )
        if work_set["work_set_hash"] != work_set_hash:
            raise ProjectTemplateError(
                "EOS_READINESS_WORK_SET_MISMATCH", "readiness WorkCodeSet drifted"
            )
        return D12ProjectBusinessReadiness(
            tenant_id=tenant_id,
            project_id=project_id,
            effective_on=effective_on,
            work_set_hash=work_set_hash,
            company_binding_ids=company_binding_ids,
            source_hash=expected_source_hash,
            work_set=work_set,
        )

    def _read_request(
        self,
        *,
        endpoint: str,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        effective_on: date | None,
    ) -> EosProjectTemplateRequest:
        contract = _EXPECTED_ENDPOINTS[endpoint]
        project_id = _uuid("project_id", project_id)
        query = (
            MappingProxyType(
                {"effective_on": _date("effective_on", effective_on).isoformat()}
            )
            if effective_on is not None
            else None
        )
        return EosProjectTemplateRequest(
            method="GET",
            path=contract["path_template"].format(project_id=project_id),
            operation_id=contract["operation_id"],
            tenant_id=_scoped_id("tenant_id", tenant_id),
            subject_id=_scoped_id("subject_id", subject_id),
            query=query,
        )


class EosProjectTemplateClient:
    def __init__(self, transport: EosProjectTemplateTransport) -> None:
        self._transport = transport

    def approve_work_set(
        self, template: D12ProjectTemplate, **runtime_bindings: Any
    ) -> Mapping[str, Any]:
        request = template.approval_request(**runtime_bindings)
        response = _object(
            self._transport.send(request), code="EOS_APPROVAL_RESPONSE_INVALID"
        )
        result = _object(response.get("result"), code="EOS_APPROVAL_RESPONSE_INVALID")
        return template.admit_work_set(
            result.get("work_set"),
            tenant_id=request.tenant_id,
            project_id=runtime_bindings["project_id"],
        )

    def get_current_work_set(
        self, template: D12ProjectTemplate, **runtime_bindings: Any
    ) -> Mapping[str, Any]:
        request = template.current_work_set_request(**runtime_bindings)
        return template.admit_work_set(
            self._transport.send(request),
            tenant_id=request.tenant_id,
            project_id=runtime_bindings["project_id"],
        )

    def require_business_ready(
        self, template: D12ProjectTemplate, **runtime_bindings: Any
    ) -> D12ProjectBusinessReadiness:
        request = template.business_readiness_request(**runtime_bindings)
        return template.require_business_ready(
            self._transport.send(request),
            tenant_id=request.tenant_id,
            project_id=runtime_bindings["project_id"],
        )


def calculate_template_digest(value: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "release_attestation"}
    )


def calculate_mandatory_codes_hash(code_ids: Sequence[str]) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-D12-MANDATORY-WORK-CODES-V1",
            "code_ids": list(code_ids),
        }
    )


def d12_project_work_set_payload_hash(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ProjectTemplateError("PAYLOAD_INVALID", "object required")
    projected = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "requested_operation",
            "trace",
        }
    }
    return nsl_write_payload_hash_ref({"operation": APPROVE_OPERATION, **projected})


def load_d12_project_template(
    path: Path = DEFAULT_TEMPLATE_PATH,
    *,
    catalog: WorkCodeCatalog | None = None,
) -> D12ProjectTemplate:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProjectTemplateError("TEMPLATE_UNREADABLE", str(path)) from error
    except json.JSONDecodeError as error:
        raise ProjectTemplateError("TEMPLATE_INVALID_JSON", str(path)) from error
    value = _object(raw, code="TEMPLATE_FIELDS_INVALID")
    if set(value) != _ROOT_FIELDS:
        raise ProjectTemplateError("TEMPLATE_FIELDS_INVALID", "root fields drifted")
    identity = tuple(
        value.get(field)
        for field in (
            "schema_version",
            "template_id",
            "template_version",
            "revision",
            "status",
        )
    )
    if identity != (
        TEMPLATE_SCHEMA_VERSION,
        TEMPLATE_ID,
        TEMPLATE_VERSION,
        1,
        TEMPLATE_STATUS,
    ):
        raise ProjectTemplateError("TEMPLATE_IDENTITY_INVALID", "identity drifted")

    catalog = catalog or load_work_code_catalog()
    binding = _object(
        value.get("catalog_binding"), code="TEMPLATE_CATALOG_BINDING_INVALID"
    )
    code_ids = _string_sequence("required_code_ids", binding.get("required_code_ids"))
    if code_ids != MANDATORY_D12_WORK_CODE_IDS:
        raise ProjectTemplateError(
            "TEMPLATE_REQUIRED_CODES_INVALID", "mandatory D12 set drifted"
        )
    expected_binding = {
        "catalog_id": catalog.catalog_id,
        "catalog_version": catalog.catalog_version,
        "catalog_digest": catalog.mapping_digest,
        "mandatory_codes_hash": calculate_mandatory_codes_hash(code_ids),
        "required_code_ids": list(code_ids),
    }
    if dict(binding) != expected_binding:
        raise ProjectTemplateError(
            "TEMPLATE_CATALOG_BINDING_INVALID", "catalog lineage drifted"
        )
    if any(
        catalog.get(code_id).required_for_project_work_set is not True
        for code_id in code_ids
    ):
        raise ProjectTemplateError(
            "TEMPLATE_REQUIRED_CODES_INVALID", "catalog code is not mandatory"
        )

    consumer = _object(
        value.get("eos_consumer_contract"), code="TEMPLATE_EOS_CONTRACT_INVALID"
    )
    if consumer.get("provider_lock_ref") != PROVIDER_LOCK_REF or any(
        consumer.get(name) != contract for name, contract in _EXPECTED_ENDPOINTS.items()
    ):
        raise ProjectTemplateError(
            "TEMPLATE_EOS_CONTRACT_INVALID", "EOS public contract drifted"
        )
    readiness = _object(
        value.get("readiness_contract"), code="TEMPLATE_READINESS_INVALID"
    )
    if dict(readiness) != _EXPECTED_READINESS:
        raise ProjectTemplateError(
            "TEMPLATE_READINESS_INVALID", "BusinessReady contract drifted"
        )
    boundaries = _object(
        value.get("runtime_boundaries"), code="TEMPLATE_BOUNDARY_INVALID"
    )
    if dict(boundaries) != _EXPECTED_BOUNDARIES:
        raise ProjectTemplateError(
            "TEMPLATE_BOUNDARY_INVALID", "runtime ownership drifted"
        )
    attestation = _object(
        value.get("release_attestation"), code="TEMPLATE_ATTESTATION_INVALID"
    )
    if (
        attestation.get("profile") != "SOURCE_AUTHORITY_CONTENT_DIGEST_V1"
        or attestation.get("authority") != "NEX_MYBEE_PHASE1_MB1_02"
        or attestation.get("evidence_ref")
        != "docs/slices/mybee_phase1_mb1_02_d12_project_template.md"
    ):
        raise ProjectTemplateError(
            "TEMPLATE_ATTESTATION_INVALID", "release authority drifted"
        )
    digest = calculate_template_digest(value)
    if digest != TEMPLATE_DIGEST or attestation.get("content_digest") != digest:
        raise ProjectTemplateError("TEMPLATE_DIGEST_MISMATCH", digest)
    return D12ProjectTemplate(
        template_id=TEMPLATE_ID,
        template_version=TEMPLATE_VERSION,
        revision=1,
        status=TEMPLATE_STATUS,
        catalog_id=CATALOG_ID,
        catalog_version=catalog.catalog_version,
        catalog_digest=catalog.mapping_digest,
        mandatory_codes_hash=expected_binding["mandatory_codes_hash"],
        required_code_ids=code_ids,
        template_digest=digest,
    )


def _object(value: object, *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectTemplateError(code, "object required")
    return value


def _string_sequence(field: str, value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProjectTemplateError(f"{field.upper()}_INVALID", "array required")
    normalized = tuple(item for item in value if isinstance(item, str) and item)
    if len(normalized) != len(value):
        raise ProjectTemplateError(f"{field.upper()}_INVALID", "text items required")
    return normalized


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise ProjectTemplateError(
            f"{field.upper()}_INVALID", "stable scoped identifier required"
        )
    return normalized


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ProjectTemplateError(
            f"{field.upper()}_INVALID", "UUID required"
        ) from error


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProjectTemplateError(
            f"{field.upper()}_INVALID", "positive integer required"
        )
    return value


def _text(field: str, value: object, *, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise ProjectTemplateError(
            f"{field.upper()}_INVALID", f"1..{maximum} characters required"
        )
    return normalized


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as error:
        raise ProjectTemplateError(
            f"{field.upper()}_INVALID", "SHA-256 hash reference required"
        ) from error


def _date(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ProjectTemplateError(f"{field.upper()}_INVALID", "date required")
    return value


def _date_text(field: str, value: object) -> date:
    if not isinstance(value, str):
        raise ProjectTemplateError(f"{field.upper()}_INVALID", "ISO date required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ProjectTemplateError(
            f"{field.upper()}_INVALID", "ISO date required"
        ) from error
