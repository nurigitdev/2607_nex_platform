from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from nex_runtime.semantic_hashes import (
    hash_ref_from_sha256,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

AGENT_CONTEXT_SCHEMA_VERSION = "1.1"
_SELECTOR_ID = re.compile(r"^E[0-9]{1,3}$")
_FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        "api_key",
        "credential",
        "credentials",
        "database_snapshot",
        "document_body",
        "hidden_reasoning",
        "provider_endpoint",
        "raw_prompt",
        "reasoning_content",
    }
)


@dataclass(frozen=True)
class AgentContextError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ContextBuildRequest:
    tenant_id: str
    principal_id: str
    agent_id: str
    execution_id: str
    workspace_id: str
    conversation_id: str
    interaction_id: str
    work_intent_ref: Mapping[str, Any]


@dataclass(frozen=True)
class TrustedContextResolution:
    project_ref: Mapping[str, Any] | None
    authority_ref: str | None
    resolved_entities: tuple[Mapping[str, Any], ...]
    retrieval_refs: tuple[Mapping[str, Any], ...]
    evidence_refs: tuple[Mapping[str, Any], ...]
    conflicts: tuple[str, ...]
    degradations: tuple[str, ...]
    context_manifest: tuple[Mapping[str, Any], ...]
    budget_tokens: int
    estimated_used_tokens: int
    truncated_optional_items: int = 0


class TrustedContextResolver(Protocol):
    def resolve(self, request: ContextBuildRequest) -> TrustedContextResolution: ...


def runtime_policy_ref_from_compatibility_policy(
    runtime_policy: Mapping[str, Any],
) -> dict[str, Any]:
    compatibility = runtime_policy.get("compatibility_rule")
    if not isinstance(compatibility, Mapping):
        raise _invalid("Compatibility runtime policy rule is required.")
    try:
        rule_hash = hash_ref_from_sha256(compatibility.get("rule_hash"))
    except ValueError as exc:
        raise _invalid("Compatibility runtime policy rule_hash is invalid.") from exc
    return _runtime_policy_ref(
        {
            "rule_id": compatibility.get("rule_id"),
            "rule_version": compatibility.get("rule_version"),
            "rule_hash": rule_hash,
        }
    )


def build_agent_context(
    *,
    tenant_id: str,
    principal_id: str,
    agent_id: str,
    execution_id: str,
    workspace_id: str,
    conversation_id: str,
    interaction_id: str,
    work_intent: Mapping[str, Any],
    runtime_policy_ref: Mapping[str, Any],
    resolver: TrustedContextResolver,
    context_id: str | None = None,
    context_generation: int = 1,
    built_at: str | None = None,
    id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    identity = {
        "tenant_id": _required_text("tenant_id", tenant_id, maximum=128),
        "principal_id": _required_text(
            "principal_id", principal_id, maximum=200
        ),
        "agent_id": _required_uuid("agent_id", agent_id),
        "agent_type": "IA",
    }
    interaction = {
        "workspace_id": _required_uuid("workspace_id", workspace_id),
        "conversation_id": _required_uuid("conversation_id", conversation_id),
        "interaction_id": _required_uuid("interaction_id", interaction_id),
    }
    execution_id = _required_uuid("execution_id", execution_id)
    work_intent_ref = _work_intent_ref(work_intent, execution_id=execution_id)
    generation = _bounded_int(
        "context_generation", context_generation, minimum=1, maximum=9999
    )
    resolved_id = _required_uuid(
        "context_id", context_id or (id_factory or (lambda: str(uuid4())))()
    )
    resolved_built_at = _required_datetime(
        "built_at",
        built_at
        or (clock or (lambda: datetime.now(UTC)))()
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    )
    policy_ref = _runtime_policy_ref(runtime_policy_ref)
    request = ContextBuildRequest(
        tenant_id=identity["tenant_id"],
        principal_id=identity["principal_id"],
        agent_id=identity["agent_id"],
        execution_id=execution_id,
        workspace_id=interaction["workspace_id"],
        conversation_id=interaction["conversation_id"],
        interaction_id=interaction["interaction_id"],
        work_intent_ref=work_intent_ref,
    )
    resolution = resolver.resolve(request)
    if not isinstance(resolution, TrustedContextResolution):
        raise _invalid("Trusted context resolver returned an unsupported result.")

    context: dict[str, Any] = {
        "schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "context_id": resolved_id,
        "context_generation": generation,
        "execution_id": execution_id,
        "work_intent_ref": work_intent_ref,
        "identity": identity,
        "interaction": interaction,
        "project_ref": _resource_ref(resolution.project_ref, nullable=True),
        "authority_ref": _optional_text(
            "authority_ref", resolution.authority_ref, maximum=256
        ),
        "resolved_entities": [
            _resolved_entity(item) for item in resolution.resolved_entities
        ],
        "retrieval_refs": [
            _resource_ref(item) for item in resolution.retrieval_refs
        ],
        "evidence_refs": [
            _resource_ref(item) for item in resolution.evidence_refs
        ],
        "runtime_policy_ref": policy_ref,
        "conflicts": _bounded_text_list(
            "conflicts", resolution.conflicts, maximum_items=32, maximum=500
        ),
        "degradations": _bounded_text_list(
            "degradations",
            resolution.degradations,
            maximum_items=32,
            maximum=500,
        ),
        "context_manifest": [
            _manifest_entry(item) for item in resolution.context_manifest
        ],
        "budget": {
            "budget_tokens": _bounded_int(
                "budget_tokens", resolution.budget_tokens, minimum=0
            ),
            "estimated_used_tokens": _bounded_int(
                "estimated_used_tokens",
                resolution.estimated_used_tokens,
                minimum=0,
            ),
            "truncated_optional_items": _bounded_int(
                "truncated_optional_items",
                resolution.truncated_optional_items,
                minimum=0,
            ),
        },
        "built_at": resolved_built_at,
    }
    _require_maximum("resolved_entities", context["resolved_entities"], 32)
    _require_maximum("retrieval_refs", context["retrieval_refs"], 64)
    _require_maximum("evidence_refs", context["evidence_refs"], 128)
    _require_maximum("context_manifest", context["context_manifest"], 256)
    if context["budget"]["estimated_used_tokens"] > context["budget"][
        "budget_tokens"
    ]:
        raise _invalid("estimated_used_tokens cannot exceed budget_tokens.")
    _reject_private_material(context)
    context["context_hash"] = semantic_sha256_hash_ref(context)
    return context


class SqlAlchemyAgentContextRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(
        self,
        *,
        tenant_id: str,
        agent_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _required_text("tenant_id", tenant_id, maximum=128)
        normalized = _validate_agent_context(agent_context)
        identity = normalized["identity"]
        interaction = normalized["interaction"]
        work_intent_ref = normalized["work_intent_ref"]
        if identity["tenant_id"] != tenant_id:
            raise _invalid("AgentContext tenant identity does not match storage scope.")
        params = {
            "tenant_id": tenant_id,
            "context_id": normalized["context_id"],
            "context_generation": normalized["context_generation"],
            "agent_execution_id": normalized["execution_id"],
            "work_intent_id": work_intent_ref["id"],
            "work_intent_revision": work_intent_ref["version"],
            "work_intent_hash": work_intent_ref["hash"],
            "principal_id": identity["principal_id"],
            "agent_id": identity["agent_id"],
            "workspace_id": interaction["workspace_id"],
            "conversation_id": interaction["conversation_id"],
            "interaction_id": interaction["interaction_id"],
            "context_hash": normalized["context_hash"],
            "context_json": _canonical_json(normalized),
            "built_at": normalized["built_at"],
        }
        try:
            with self._session_factory() as session:
                _require_persisted_lineage(session, params)
                _require_previous_generation(session, params)
                session.execute(
                    text(_context_insert_sql(_dialect_name(session))), params
                )
                saved = _load_context(
                    session, tenant_id, str(normalized["context_id"])
                )
                if saved is None:
                    conflict = _load_context_by_generation(
                        session,
                        tenant_id,
                        str(normalized["execution_id"]),
                        int(normalized["context_generation"]),
                    )
                    if conflict is not None:
                        raise AgentContextError(
                            "ae.agent_context_generation_conflict",
                            "A different AgentContext owns this execution generation.",
                        )
                    raise AgentContextError(
                        "ae.agent_context_write_conflict",
                        "AgentContext could not be reloaded after persistence.",
                        True,
                    )
                if saved != normalized:
                    raise AgentContextError(
                        "ae.agent_context_immutable_conflict",
                        "AgentContext identity exists with different content.",
                    )
                session.commit()
                return saved
        except AgentContextError:
            raise
        except SQLAlchemyError as exc:
            raise AgentContextError(
                "ae.agent_context_store_unavailable",
                "AE AgentContext store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, context_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, maximum=128)
        context_id = _required_uuid("context_id", context_id)
        try:
            with self._session_factory() as session:
                return _load_context(session, tenant_id, context_id)
        except SQLAlchemyError as exc:
            raise AgentContextError(
                "ae.agent_context_store_unavailable",
                "AE AgentContext store is unavailable.",
                True,
            ) from exc


def _validate_agent_context(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("AgentContext must be canonical JSON.") from exc
    if record.get("schema_version") != AGENT_CONTEXT_SCHEMA_VERSION:
        raise _invalid("AgentContext schema_version must be 1.1.")
    _require_object_fields(
        "AgentContext",
        record,
        required={
            "schema_version",
            "context_id",
            "context_generation",
            "execution_id",
            "work_intent_ref",
            "identity",
            "interaction",
            "project_ref",
            "resolved_entities",
            "retrieval_refs",
            "evidence_refs",
            "runtime_policy_ref",
            "conflicts",
            "degradations",
            "context_manifest",
            "budget",
            "context_hash",
            "built_at",
        },
        optional={"authority_ref"},
    )
    _required_uuid("context_id", record.get("context_id"))
    _bounded_int(
        "context_generation",
        record.get("context_generation"),
        minimum=1,
        maximum=9999,
    )
    _required_uuid("execution_id", record.get("execution_id"))
    work_intent_ref = _versioned_hash_ref(
        "work_intent_ref", record.get("work_intent_ref")
    )
    identity = record.get("identity")
    interaction = record.get("interaction")
    if not isinstance(identity, dict) or identity.get("agent_type") != "IA":
        raise _invalid("AgentContext identity must describe an IA.")
    _require_object_fields(
        "identity",
        identity,
        required={"tenant_id", "principal_id", "agent_id", "agent_type"},
    )
    _required_text("tenant_id", identity.get("tenant_id"), maximum=128)
    _required_text("principal_id", identity.get("principal_id"), maximum=200)
    _required_uuid("agent_id", identity.get("agent_id"))
    if not isinstance(interaction, dict):
        raise _invalid("AgentContext interaction is required.")
    _require_object_fields(
        "interaction",
        interaction,
        required={"workspace_id", "conversation_id", "interaction_id"},
    )
    for field in ("workspace_id", "conversation_id", "interaction_id"):
        _required_uuid(field, interaction.get(field))
    _resource_ref(record.get("project_ref"), nullable=True)
    _optional_text("authority_ref", record.get("authority_ref"), maximum=256)
    for field, maximum in (
        ("resolved_entities", 32),
        ("retrieval_refs", 64),
        ("evidence_refs", 128),
        ("context_manifest", 256),
    ):
        items = record.get(field)
        if not isinstance(items, list):
            raise _invalid(f"{field} must be an array.")
        _require_maximum(field, items, maximum)
    for item in record["resolved_entities"]:
        _resolved_entity(item)
    for field in ("retrieval_refs", "evidence_refs"):
        for item in record[field]:
            _resource_ref(item)
    _runtime_policy_ref(record.get("runtime_policy_ref"))
    _bounded_text_list("conflicts", record.get("conflicts"), 32, 500)
    _bounded_text_list("degradations", record.get("degradations"), 32, 500)
    for item in record["context_manifest"]:
        _manifest_entry(item)
    budget = record.get("budget")
    if not isinstance(budget, dict):
        raise _invalid("AgentContext budget is required.")
    _require_object_fields(
        "budget",
        budget,
        required={
            "budget_tokens",
            "estimated_used_tokens",
            "truncated_optional_items",
        },
    )
    budget_tokens = _bounded_int(
        "budget_tokens", budget.get("budget_tokens"), minimum=0
    )
    used = _bounded_int(
        "estimated_used_tokens", budget.get("estimated_used_tokens"), minimum=0
    )
    _bounded_int(
        "truncated_optional_items",
        budget.get("truncated_optional_items"),
        minimum=0,
    )
    if used > budget_tokens:
        raise _invalid("estimated_used_tokens cannot exceed budget_tokens.")
    _required_datetime("built_at", record.get("built_at"))
    try:
        validate_hash_ref(record.get("context_hash"))
    except ValueError as exc:
        raise _invalid("AgentContext context_hash is invalid.") from exc
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "context_hash"}
    )
    if record["context_hash"] != expected_hash:
        raise _invalid("AgentContext context_hash does not match its content.")
    if work_intent_ref["id"] == record["context_id"]:
        raise _invalid("AgentContext and WorkIntent identities must differ.")
    _reject_private_material(record)
    return record


def _work_intent_ref(
    work_intent: Mapping[str, Any], *, execution_id: str
) -> dict[str, Any]:
    if work_intent.get("execution_id") != execution_id:
        raise _invalid("WorkIntent execution does not match AgentContext execution.")
    return _versioned_hash_ref(
        "work_intent_ref",
        {
            "id": work_intent.get("work_intent_id"),
            "version": work_intent.get("intent_revision"),
            "hash": work_intent.get("intent_hash"),
        },
    )


def _versioned_hash_ref(field: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"id", "version", "hash"}:
        raise _invalid(f"{field} must be an exact versioned hash reference.")
    try:
        hash_ref = validate_hash_ref(value.get("hash"))
    except ValueError as exc:
        raise _invalid(f"{field}.hash is invalid.") from exc
    return {
        "id": _required_uuid(f"{field}.id", value.get("id")),
        "version": _bounded_int(
            f"{field}.version", value.get("version"), minimum=1
        ),
        "hash": hash_ref,
    }


def _runtime_policy_ref(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "rule_id",
        "rule_version",
        "rule_hash",
    }:
        raise _invalid("runtime_policy_ref must be an exact policy reference.")
    try:
        rule_hash = validate_hash_ref(value.get("rule_hash"))
    except ValueError as exc:
        raise _invalid("runtime_policy_ref.rule_hash is invalid.") from exc
    return {
        "rule_id": _required_text("rule_id", value.get("rule_id"), maximum=160),
        "rule_version": _required_text(
            "rule_version", value.get("rule_version"), maximum=64
        ),
        "rule_hash": rule_hash,
    }


def _resource_ref(
    value: object, *, nullable: bool = False
) -> dict[str, Any] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, Mapping):
        raise _invalid("Resource reference must be an object.")
    allowed = {"system", "resource_type", "resource_id", "version"}
    if not set(value).issubset(allowed) or not {
        "system",
        "resource_type",
        "resource_id",
    }.issubset(value):
        raise _invalid("Resource reference fields are invalid.")
    return {
        "system": _required_text("system", value.get("system"), maximum=64),
        "resource_type": _required_text(
            "resource_type", value.get("resource_type"), maximum=64
        ),
        "resource_id": _required_text(
            "resource_id", value.get("resource_id"), maximum=200
        ),
        **(
            {
                "version": _optional_text(
                    "version", value.get("version"), maximum=128
                )
            }
            if "version" in value
            else {}
        ),
    }


def _resolved_entity(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "selector_id",
        "resource_ref",
        "source_ref",
        "resolved_at",
    }:
        raise _invalid("Resolved entity fields are invalid.")
    selector_id = _required_text(
        "selector_id", value.get("selector_id"), maximum=4
    )
    if _SELECTOR_ID.fullmatch(selector_id) is None:
        raise _invalid("selector_id must use E<number> form.")
    return {
        "selector_id": selector_id,
        "resource_ref": _resource_ref(value.get("resource_ref")),
        "source_ref": _required_text(
            "source_ref", value.get("source_ref"), maximum=256
        ),
        "resolved_at": _required_datetime("resolved_at", value.get("resolved_at")),
    }


def _manifest_entry(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Context manifest entry must be an object.")
    allowed = {"kind", "source_ref", "source_version", "content_hash", "as_of"}
    if not set(value).issubset(allowed) or not {
        "kind",
        "source_ref",
        "content_hash",
        "as_of",
    }.issubset(value):
        raise _invalid("Context manifest entry fields are invalid.")
    try:
        content_hash = validate_hash_ref(value.get("content_hash"))
    except ValueError as exc:
        raise _invalid("Context manifest content_hash is invalid.") from exc
    return {
        "kind": _required_text("kind", value.get("kind"), maximum=64),
        "source_ref": _required_text(
            "source_ref", value.get("source_ref"), maximum=256
        ),
        **(
            {
                "source_version": _optional_text(
                    "source_version", value.get("source_version"), maximum=128
                )
            }
            if "source_version" in value
            else {}
        ),
        "content_hash": content_hash,
        "as_of": _required_datetime("as_of", value.get("as_of")),
    }


def _require_persisted_lineage(session: Session, params: Mapping[str, Any]) -> None:
    intent = session.execute(
        text(
            """
            SELECT agent_execution_id, intent_revision, intent_hash
            FROM ae_work_intent
            WHERE tenant_id = :tenant_id AND work_intent_id = :work_intent_id
            """
        ),
        params,
    ).mappings().first()
    if (
        intent is None
        or str(intent["agent_execution_id"]) != params["agent_execution_id"]
        or int(intent["intent_revision"]) != params["work_intent_revision"]
        or intent["intent_hash"] != params["work_intent_hash"]
    ):
        raise AgentContextError(
            "ae.agent_context_work_intent_mismatch",
            "AgentContext does not reference the exact persisted WorkIntent.",
        )
    execution = session.execute(
        text(
            """
            SELECT principal_id, agent_id, agent_type, workspace_id,
                   conversation_id, legacy_interaction_id
            FROM ae_agent_execution
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :agent_execution_id
            """
        ),
        params,
    ).mappings().first()
    if execution is None:
        raise AgentContextError(
            "ae.agent_context_execution_not_found",
            "AgentContext AgentExecution was not found.",
        )
    expected = (
        ("principal_id", params["principal_id"]),
        ("agent_id", params["agent_id"]),
        ("agent_type", "IA"),
        ("workspace_id", params["workspace_id"]),
        ("conversation_id", params["conversation_id"]),
        ("legacy_interaction_id", params["interaction_id"]),
    )
    if any(str(execution[field]) != str(value) for field, value in expected):
        raise AgentContextError(
            "ae.agent_context_execution_scope_mismatch",
            "AgentContext identity or interaction does not match AgentExecution.",
        )


def _require_previous_generation(session: Session, params: Mapping[str, Any]) -> None:
    generation = int(params["context_generation"])
    if generation == 1:
        return
    previous = _load_context_by_generation(
        session,
        str(params["tenant_id"]),
        str(params["agent_execution_id"]),
        generation - 1,
    )
    if previous is None:
        raise AgentContextError(
            "ae.agent_context_generation_chain_invalid",
            "AgentContext generation must follow the preceding generation.",
        )


def _context_insert_sql(dialect_name: str) -> str:
    context_json = (
        "CAST(:context_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":context_json"
    )
    return f"""
        INSERT INTO ae_agent_context (
            tenant_id, context_id, context_generation, agent_execution_id,
            work_intent_id, work_intent_revision, work_intent_hash,
            principal_id, agent_id, workspace_id, conversation_id,
            interaction_id, context_hash, context_json, built_at
        ) VALUES (
            :tenant_id, :context_id, :context_generation, :agent_execution_id,
            :work_intent_id, :work_intent_revision, :work_intent_hash,
            :principal_id, :agent_id, :workspace_id, :conversation_id,
            :interaction_id, :context_hash, {context_json}, :built_at
        ) ON CONFLICT DO NOTHING
    """


def _load_context(
    session: Session, tenant_id: str, context_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT context_json FROM ae_agent_context
            WHERE tenant_id = :tenant_id AND context_id = :context_id
            """
        ),
        {"tenant_id": tenant_id, "context_id": context_id},
    ).mappings().first()
    return None if row is None else _json_value(row["context_json"])


def _load_context_by_generation(
    session: Session, tenant_id: str, execution_id: str, generation: int
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT context_json FROM ae_agent_context
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
              AND context_generation = :generation
            """
        ),
        {
            "tenant_id": tenant_id,
            "execution_id": execution_id,
            "generation": generation,
        },
    ).mappings().first()
    return None if row is None else _json_value(row["context_json"])


def _reject_private_material(value: Any) -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_PRIVATE_KEYS.intersection(value)
        if forbidden:
            raise _invalid(
                f"AgentContext contains forbidden private field: {min(forbidden)}."
            )
        for item in value.values():
            _reject_private_material(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_private_material(item)


def _bounded_text_list(
    field: str,
    value: object,
    maximum_items: int,
    maximum: int,
) -> list[str]:
    if not isinstance(value, list | tuple):
        raise _invalid(f"{field} must be an array.")
    _require_maximum(field, value, maximum_items)
    return [_required_text(field, item, maximum=maximum) for item in value]


def _require_maximum(field: str, value: Any, maximum: int) -> None:
    if len(value) > maximum:
        raise _invalid(f"{field} exceeds its maximum item count.")


def _require_object_fields(
    field: str,
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    actual = set(value)
    allowed = required | (optional or set())
    if not required.issubset(actual) or not actual.issubset(allowed):
        raise _invalid(f"{field} fields do not match the v1.1 contract.")


def _bounded_int(
    field: str, value: object, *, minimum: int, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _invalid(f"{field} must be an integer of at least {minimum}.")
    if maximum is not None and value > maximum:
        raise _invalid(f"{field} must not exceed {maximum}.")
    return value


def _required_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _required_text(field: str, value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty string up to {maximum} characters.")
    return value.strip()


def _optional_text(field: str, value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(field, value, maximum=maximum)


def _required_datetime(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC 3339 date-time string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 date-time string.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_value(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> AgentContextError:
    return AgentContextError("ae.agent_context_invalid", detail)
