from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

GOVERNED_WRITE_POLICY_ID = "platform.governed-write"
GOVERNED_WRITE_POLICY_VERSION = "2.1"
_ASSURANCE_ORDER = {"NONE": 0, "STANDARD": 1, "HIGH": 2, "CRITICAL": 3}
_AUTHORIZATION_FIELDS = frozenset(
    {
        "tenant_id",
        "business_operation_id",
        "oa_decision_ref",
        "oa_allowed",
        "protected_operation",
        "operation_trust_decision",
        "required_assurance_level",
    }
)
_DESCRIPTOR_REQUIRED_FIELDS = frozenset(
    {
        "tenant_id",
        "agent_execution_id",
        "executable_step_id",
        "business_operation_id",
        "project_ref",
        "capability",
        "operation_class",
        "business_object_type",
        "typed_parameters",
        "operation_fingerprint",
    }
)
_DESCRIPTOR_OPTIONAL_FIELDS = frozenset(
    {
        "actor_ref",
        "agent_ref",
        "org_scope_refs",
        "resource_refs",
        "data_classification",
    }
)
_TRUST_REQUIRED_FIELDS = frozenset(
    {
        "decision",
        "decision_mode",
        "assurance_level",
        "operation_fingerprint",
        "facts_hash",
        "decision_hash",
        "evaluated_at",
        "expires_at",
    }
)
_TRUST_OPTIONAL_FIELDS = frozenset(
    {"rule_set_ref", "rule_set_version", "reason_code", "proof_ref"}
)


class GovernedWriteAuthorizationSource(Protocol):
    def resolve(self, request: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class PlatformRuntimePolicyError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class _Authorization:
    tenant_id: str
    business_operation_id: str
    oa_decision_ref: str
    oa_allowed: bool
    descriptor: dict[str, Any]
    trust: dict[str, Any]
    required_assurance_level: str
    evaluated_at: datetime
    expires_at: datetime


class PlatformRuntimePolicyAdapter:
    """Project Platform authority into the admitted NSL RuntimePolicyPort."""

    def __init__(
        self,
        *,
        authorization_source: GovernedWriteAuthorizationSource,
        public_api: NslV02PublicApiAdapter,
    ) -> None:
        if not isinstance(public_api, NslV02PublicApiAdapter):
            raise _invalid("NSL runtime policy requires the admitted public API.")
        for name in (
            "runtime_policy_port",
            "write_policy_request",
            "policy_decision",
            "policy_effect",
        ):
            if not isinstance(getattr(public_api, name, None), type):
                raise _invalid(f"Admitted NSL {name} is unavailable.")
        self._authorization_source = authorization_source
        self._public_api = public_api

    def authorize_write(self, request: Any) -> Any:
        if not isinstance(request, self._public_api.write_policy_request):
            raise _invalid("NSL write policy request type is invalid.")
        try:
            raw = self._authorization_source.resolve(request)
        except PlatformRuntimePolicyError:
            raise
        except Exception as exc:
            raise PlatformRuntimePolicyError(
                "ae.nsl_runtime_policy_authority_unavailable",
                "Governed WRITE authorization is unavailable.",
            ) from exc

        authority = _authorization(raw)
        allowed = _allows(request, authority)
        effect = (
            self._public_api.policy_effect.ALLOW
            if allowed
            else self._public_api.policy_effect.DENY
        )
        trust = authority.trust
        try:
            decision = self._public_api.policy_decision(
                decision_id=trust["decision_hash"],
                policy_id=_optional_text(trust.get("rule_set_ref"))
                or GOVERNED_WRITE_POLICY_ID,
                policy_version=_optional_text(trust.get("rule_set_version"))
                or GOVERNED_WRITE_POLICY_VERSION,
                effect=effect,
                tenant_id=request.tenant_id,
                subject_id=request.subject_id,
                action=request.action,
                tool_id=request.tool_id,
                risk_level=request.risk_level,
                business_operation_id=request.business_operation_id,
                write_node_id=request.write_node_id,
                write_intent_hash=request.write_intent_hash,
                evidence_ref=authority.oa_decision_ref,
                evaluated_at=authority.evaluated_at,
                expires_at=authority.expires_at,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise _invalid("Admitted NSL PolicyDecision is incompatible.") from exc
        try:
            compatible = (
                isinstance(decision, self._public_api.policy_decision)
                and callable(getattr(decision, "matches", None))
                and decision.matches(request) is True
                and decision.effect is effect
            )
        except Exception as exc:
            raise _invalid("NSL PolicyDecision compatibility check failed.") from exc
        if not compatible:
            raise _invalid("NSL PolicyDecision changed governed WRITE bindings.")
        return decision


def _authorization(value: object) -> _Authorization:
    data = _mapping(value, "GovernedWriteAuthorization")
    _exact_fields(data, _AUTHORIZATION_FIELDS, frozenset(), "authorization")
    descriptor = _mapping(data.get("protected_operation"), "protected_operation")
    _exact_fields(
        descriptor,
        _DESCRIPTOR_REQUIRED_FIELDS,
        _DESCRIPTOR_OPTIONAL_FIELDS,
        "protected_operation",
    )
    trust = _mapping(
        data.get("operation_trust_decision"), "operation_trust_decision"
    )
    _exact_fields(
        trust,
        _TRUST_REQUIRED_FIELDS,
        _TRUST_OPTIONAL_FIELDS,
        "operation_trust_decision",
    )

    tenant_id = _text(data.get("tenant_id"), "tenant_id")
    business_operation_id = _text(
        data.get("business_operation_id"), "business_operation_id"
    )
    oa_decision_ref = _text(data.get("oa_decision_ref"), "oa_decision_ref")
    if data.get("oa_allowed") is not True:
        raise _invalid("GovernedWriteAuthorization requires current OA ALLOW.")
    required_assurance = _assurance(
        data.get("required_assurance_level"), "required_assurance_level"
    )
    _validate_descriptor(descriptor)
    evaluated_at, expires_at = _validate_trust(trust)
    return _Authorization(
        tenant_id=tenant_id,
        business_operation_id=business_operation_id,
        oa_decision_ref=oa_decision_ref,
        oa_allowed=data["oa_allowed"],
        descriptor=dict(descriptor),
        trust=dict(trust),
        required_assurance_level=required_assurance,
        evaluated_at=evaluated_at,
        expires_at=expires_at,
    )


def _validate_descriptor(value: Mapping[str, Any]) -> None:
    for field in _DESCRIPTOR_REQUIRED_FIELDS - {"typed_parameters"}:
        _text(value.get(field), f"protected_operation.{field}")
    if not isinstance(value.get("typed_parameters"), Mapping):
        raise _invalid("Protected operation typed_parameters must be an object.")
    for field in ("actor_ref", "agent_ref", "data_classification"):
        if value.get(field) is not None:
            _text(value.get(field), f"protected_operation.{field}")
    for field in ("org_scope_refs", "resource_refs"):
        if field in value:
            _text_list(value.get(field), f"protected_operation.{field}")


def _validate_trust(value: Mapping[str, Any]) -> tuple[datetime, datetime]:
    decision = _text(value.get("decision"), "operation_trust_decision.decision")
    if decision not in {"ALLOW", "DENY", "REVIEW", "INDETERMINATE"}:
        raise _invalid("Operation trust decision is invalid.")
    for field in (
        "decision_mode",
        "operation_fingerprint",
        "facts_hash",
        "decision_hash",
    ):
        _text(value.get(field), f"operation_trust_decision.{field}")
    _assurance(value.get("assurance_level"), "operation_trust_decision.assurance_level")
    for field in _TRUST_OPTIONAL_FIELDS:
        if value.get(field) is not None:
            _text(value.get(field), f"operation_trust_decision.{field}")
    evaluated_at = _utc(value.get("evaluated_at"), "evaluated_at")
    expires_at = _utc(value.get("expires_at"), "expires_at")
    if expires_at <= evaluated_at:
        raise _invalid("Operation trust decision expiry must follow evaluation.")
    return evaluated_at, expires_at


def _allows(request: Any, authority: _Authorization) -> bool:
    descriptor = authority.descriptor
    trust = authority.trust
    actor_ref = _optional_text(descriptor.get("actor_ref"))
    return all(
        (
            authority.oa_allowed,
            authority.tenant_id == request.tenant_id,
            authority.business_operation_id == str(request.business_operation_id),
            descriptor["tenant_id"] == request.tenant_id,
            descriptor["business_operation_id"]
            == str(request.business_operation_id),
            descriptor["capability"] == "WRITE",
            actor_ref is None or actor_ref == request.subject_id,
            trust["decision"] == "ALLOW",
            trust["operation_fingerprint"] == descriptor["operation_fingerprint"],
            _ASSURANCE_ORDER[trust["assurance_level"]]
            >= _ASSURANCE_ORDER[authority.required_assurance_level],
            trust["decision_mode"] != "DUMMY_ALWAYS_ALLOW"
            or authority.required_assurance_level == "NONE",
        )
    )


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object.")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    required: frozenset[str],
    optional: frozenset[str],
    field: str,
) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise _invalid(f"{field} fields do not match the frozen contract.")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise _invalid(f"{field} must be a string list.")
    return tuple(item.strip() for item in value)


def _assurance(value: object, field: str) -> str:
    normalized = _text(value, field)
    if normalized not in _ASSURANCE_ORDER:
        raise _invalid(f"{field} is unsupported.")
    return normalized


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"Operation trust {field} must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"Operation trust {field} must be an ISO timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise _invalid(f"Operation trust {field} must use UTC.")
    return parsed


def _invalid(detail: str) -> PlatformRuntimePolicyError:
    return PlatformRuntimePolicyError("ae.nsl_runtime_policy_invalid", detail)
