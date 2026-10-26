from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_backend_profiles import (
    DEFAULT_NSL_V01_BACKEND_PROFILE,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    normalize_nsl_backend_profile,
)
from nex_ae_api.planning_capabilities import validate_local_skill_binding
from nex_ae_api.skill_artifacts import validate_verified_skill_artifact

BACKEND_PROFILE = DEFAULT_NSL_V01_BACKEND_PROFILE
CONTEXT_PROJECTION_SCHEMA_VERSION = "1.0"
SKILL_EXECUTION_REQUEST_SCHEMA_VERSION = "1.0"
NSL_STEP_BINDING_SCHEMA_VERSION = "1.0"
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_SELECTOR = re.compile(r"^[\x21-\x7e]{1,256}$")
_CONTEXT_PATH = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){0,7}$")
_CLASSIFICATIONS = frozenset({"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"})
_PROVENANCE = frozenset({"USER", "CONTEXT", "DEFAULT"})
_BINDING_STATES = frozenset(
    {
        "ALLOCATED",
        "REQUEST_BOUND",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
    }
)
_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"})
_FORBIDDEN_KEYS = frozenset(
    {
        "agent_context",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "document_body",
        "hidden_reasoning",
        "password",
        "prompt",
        "provider_endpoint",
        "raw_content",
        "raw_prompt",
        "reasoning_content",
        "secret",
        "token",
    }
)


@dataclass(frozen=True)
class NSLStepExecutionError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_context_projection(
    *,
    agent_context_ref: str,
    agent_context_hash: str,
    runtime_context_entries: Sequence[Mapping[str, Any]],
    explicit_resource_refs: Sequence[str],
    verified_principal: Mapping[str, Any],
    authority: Mapping[str, Any],
    data_policy: Mapping[str, Any],
) -> dict[str, Any]:
    projection = {
        "schema_version": CONTEXT_PROJECTION_SCHEMA_VERSION,
        "agent_context_ref": agent_context_ref,
        "agent_context_hash": agent_context_hash,
        "runtime_context_entries": list(runtime_context_entries),
        "explicit_resource_refs": list(explicit_resource_refs),
        "verified_principal": dict(verified_principal),
        "authority": dict(authority),
        "data_policy": dict(data_policy),
    }
    projection["projection_hash"] = semantic_sha256_hash_ref(projection)
    return validate_context_projection(projection)


def validate_context_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    projection = _canonical_mapping("ContextProjection", value)
    fields = {
        "schema_version",
        "agent_context_ref",
        "agent_context_hash",
        "runtime_context_entries",
        "explicit_resource_refs",
        "verified_principal",
        "authority",
        "data_policy",
        "projection_hash",
    }
    if set(projection) != fields or projection.get("schema_version") != "1.0":
        raise _invalid("ContextProjection fields or schema version are invalid.")
    _ref("agent_context_ref", projection["agent_context_ref"])
    _hash("agent_context_hash", projection["agent_context_hash"])
    entries = projection["runtime_context_entries"]
    if not isinstance(entries, list) or len(entries) > 64:
        raise _invalid("runtime_context_entries must be a bounded array.")
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "path",
            "value",
            "classification",
            "source_ref",
        }:
            raise _invalid("ContextProjection runtime entry is invalid.")
        path = entry["path"]
        if not isinstance(path, str) or _CONTEXT_PATH.fullmatch(path) is None:
            raise _invalid("ContextProjection runtime entry path is invalid.")
        if path in seen_paths or any(
            part.lower() in _FORBIDDEN_KEYS for part in path.split(".")
        ):
            raise _invalid(
                "ContextProjection runtime entry path is duplicated or private."
            )
        seen_paths.add(path)
        if entry["classification"] not in _CLASSIFICATIONS:
            raise _invalid("ContextProjection classification is invalid.")
        _ref("source_ref", entry["source_ref"])
        _reject_private_material(entry["value"])
    refs = _refs("explicit_resource_refs", projection["explicit_resource_refs"], 64)
    if refs != projection["explicit_resource_refs"]:
        raise _invalid("ContextProjection resource references must be canonical.")
    principal = projection["verified_principal"]
    if not isinstance(principal, Mapping) or set(principal) != {
        "tenant_id",
        "subject_id",
        "actor_type",
        "roles",
        "scopes",
        "auth_context_ref",
        "verification",
        "on_behalf_of",
    }:
        raise _invalid("ContextProjection verified principal is invalid.")
    for field in ("tenant_id", "subject_id", "actor_type"):
        _text(field, principal[field], 256)
    _text_list("roles", principal["roles"], 64)
    _text_list("scopes", principal["scopes"], 128)
    _ref("auth_context_ref", principal["auth_context_ref"])
    if principal["verification"] != "VERIFIED":
        raise _invalid("ContextProjection principal is not verified.")
    _optional_text("on_behalf_of", principal["on_behalf_of"], 256)
    authority = projection["authority"]
    if not isinstance(authority, Mapping) or set(authority) != {
        "effective_role_bindings",
        "org_scope",
        "project_scope",
    }:
        raise _invalid("ContextProjection authority is invalid.")
    _text_list("effective_role_bindings", authority["effective_role_bindings"], 64)
    _text_list("org_scope", authority["org_scope"], 64)
    if authority["project_scope"] is not None:
        _text_list("project_scope", authority["project_scope"], 64)
    policy = projection["data_policy"]
    if not isinstance(policy, Mapping) or set(policy) != {
        "policy_ref",
        "max_trace_classification",
        "snapshot_retention_days",
        "audit_retention_days",
    }:
        raise _invalid("ContextProjection data policy is invalid.")
    _ref("policy_ref", policy["policy_ref"])
    if policy["max_trace_classification"] not in _CLASSIFICATIONS:
        raise _invalid("ContextProjection policy classification is invalid.")
    _bounded_int("snapshot_retention_days", policy["snapshot_retention_days"], 0, 3650)
    _bounded_int("audit_retention_days", policy["audit_retention_days"], 0, 3650)
    supplied_hash = _hash("projection_hash", projection["projection_hash"])
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in projection.items() if key != "projection_hash"}
    )
    if supplied_hash != expected:
        raise _invalid("ContextProjection hash does not match semantic content.")
    return projection


def build_skill_execution_request(
    *,
    tenant_id: str,
    agent_execution_id: str,
    executable_plan_id: str,
    executable_step_id: str,
    nsl_execution_id: str,
    business_operation_id: str,
    artifact: Mapping[str, Any],
    compiled_inputs: Mapping[str, Any],
    input_provenance: Mapping[str, str],
    context_projection: Mapping[str, Any],
    context_projection_ref: str,
    correlation_id: str,
    causation_id: str | None,
) -> dict[str, Any]:
    verified_artifact = validate_verified_skill_artifact(artifact)
    context = validate_context_projection(context_projection)
    request = {
        "schema_version": SKILL_EXECUTION_REQUEST_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "agent_execution_id": agent_execution_id,
        "executable_plan_id": executable_plan_id,
        "executable_step_id": executable_step_id,
        "nsl_execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
        "skill_id": verified_artifact["skill_id"],
        "exact_skill_version": verified_artifact["skill_version"],
        "expected_semantic_hash": verified_artifact["skill_semantic_hash"],
        "runtime_contract_ref": verified_artifact["runtime_contract_ref"],
        "compiled_inputs": dict(compiled_inputs),
        "input_provenance": dict(input_provenance),
        "explicit_resource_refs": list(context["explicit_resource_refs"]),
        "principal_context_ref": context["verified_principal"]["auth_context_ref"],
        "data_policy_ref": context["data_policy"]["policy_ref"],
        "context_projection_ref": context_projection_ref,
        "context_projection_hash": context["projection_hash"],
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "agent_context_ref": context["agent_context_ref"],
        "agent_context_hash": context["agent_context_hash"],
        "mode": "NEW",
    }
    return validate_skill_execution_request(request)


def validate_skill_execution_request(value: Mapping[str, Any]) -> dict[str, Any]:
    request = _canonical_mapping("SkillExecutionRequest", value)
    fields = {
        "schema_version",
        "tenant_id",
        "agent_execution_id",
        "executable_plan_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
        "skill_id",
        "exact_skill_version",
        "expected_semantic_hash",
        "runtime_contract_ref",
        "compiled_inputs",
        "input_provenance",
        "explicit_resource_refs",
        "principal_context_ref",
        "data_policy_ref",
        "context_projection_ref",
        "context_projection_hash",
        "correlation_id",
        "causation_id",
        "agent_context_ref",
        "agent_context_hash",
        "mode",
    }
    if set(request) != fields or request.get("schema_version") != "1.0":
        raise _invalid("SkillExecutionRequest fields or schema version are invalid.")
    _text("tenant_id", request["tenant_id"], 256)
    identity_fields = (
        "agent_execution_id",
        "executable_plan_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
    )
    identities = [_uuid(field, request[field]) for field in identity_fields]
    if len(set(identities)) != len(identities):
        raise _invalid("SkillExecutionRequest identities must remain distinct.")
    _selector("skill_id", request["skill_id"])
    _selector("exact_skill_version", request["exact_skill_version"])
    _hash("expected_semantic_hash", request["expected_semantic_hash"])
    _ref("runtime_contract_ref", request["runtime_contract_ref"])
    inputs = request["compiled_inputs"]
    provenance = request["input_provenance"]
    if (
        not isinstance(inputs, Mapping)
        or not isinstance(provenance, Mapping)
        or len(inputs) > 128
    ):
        raise _invalid("SkillExecutionRequest inputs are invalid.")
    if set(inputs) != set(provenance):
        raise _invalid("Input provenance must exactly cover compiled inputs.")
    for name, source in provenance.items():
        if (
            not isinstance(name, str)
            or _SAFE_NAME.fullmatch(name) is None
            or source not in _PROVENANCE
        ):
            raise _invalid("SkillExecutionRequest input provenance is invalid.")
    _reject_private_material(inputs)
    refs = _refs("explicit_resource_refs", request["explicit_resource_refs"], 64)
    if refs != request["explicit_resource_refs"]:
        raise _invalid("SkillExecutionRequest resource references must be canonical.")
    for field in (
        "principal_context_ref",
        "data_policy_ref",
        "context_projection_ref",
        "agent_context_ref",
    ):
        _ref(field, request[field])
    for field in ("context_projection_hash", "agent_context_hash"):
        _hash(field, request[field])
    _text("correlation_id", request["correlation_id"], 256)
    _optional_text("causation_id", request["causation_id"], 256)
    if request["mode"] != "NEW":
        raise _invalid("SkillExecutionRequest mode must be NEW.")
    return request


def validate_nsl_step_execution_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    binding = _canonical_mapping("NSLStepExecutionBinding", value)
    fields = {
        "schema_version",
        "tenant_id",
        "agent_execution_id",
        "executable_plan_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
        "skill_id",
        "exact_skill_version",
        "skill_semantic_hash",
        "verified_artifact_ref",
        "verified_artifact_hash",
        "request_ref",
        "request_hash",
        "backend_profile",
        "state",
        "result_summary_ref",
        "result_summary_hash",
        "allocated_at",
        "request_bound_at",
        "invocation_started_at",
        "completed_at",
        "created_at",
        "updated_at",
    }
    if set(binding) != fields or binding.get("schema_version") != "1.0":
        raise _invalid("NSLStepExecutionBinding fields or schema version are invalid.")
    _text("tenant_id", binding["tenant_id"], 256)
    identities = [
        _uuid(field, binding[field])
        for field in (
            "agent_execution_id",
            "executable_plan_id",
            "executable_step_id",
            "nsl_execution_id",
            "business_operation_id",
        )
    ]
    if len(set(identities)) != len(identities):
        raise _invalid("NSLStepExecutionBinding identities must remain distinct.")
    _selector("skill_id", binding["skill_id"])
    _selector("exact_skill_version", binding["exact_skill_version"])
    for field in ("skill_semantic_hash", "verified_artifact_hash", "request_hash"):
        _hash(field, binding[field])
    for field in ("verified_artifact_ref", "request_ref"):
        _ref(field, binding[field])
    try:
        normalize_nsl_backend_profile(binding["backend_profile"])
    except ValueError as exc:
        raise _invalid("NSLStepExecutionBinding backend profile is invalid.") from exc
    if binding["state"] not in _BINDING_STATES:
        raise _invalid("NSLStepExecutionBinding backend profile or state is invalid.")
    state = binding["state"]
    for field in ("allocated_at", "created_at", "updated_at"):
        _timestamp(field, binding[field])
    for field in ("request_bound_at", "invocation_started_at", "completed_at"):
        _optional_timestamp(field, binding[field])
    _optional_ref("result_summary_ref", binding["result_summary_ref"])
    _optional_hash("result_summary_hash", binding["result_summary_hash"])
    if state == "ALLOCATED" and binding["request_bound_at"] is not None:
        raise _invalid("ALLOCATED binding cannot have request-bound evidence.")
    if state != "ALLOCATED" and binding["request_bound_at"] is None:
        raise _invalid("Bound NSL execution requires request_bound_at.")
    if state == "RUNNING" and binding["invocation_started_at"] is None:
        raise _invalid("RUNNING binding requires invocation_started_at.")
    if state in _TERMINAL_STATES:
        required = (
            binding["result_summary_ref"],
            binding["result_summary_hash"],
            binding["invocation_started_at"],
            binding["completed_at"],
        )
        if any(item is None for item in required):
            raise _invalid("Terminal binding requires complete result evidence.")
    elif any(
        binding[field] is not None
        for field in ("result_summary_ref", "result_summary_hash", "completed_at")
    ):
        raise _invalid("Non-terminal binding cannot have terminal result evidence.")
    return binding


class SqlAlchemyNSLStepExecutionRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def bind_request(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        verified_artifact_ref: str,
        context_projection: Mapping[str, Any],
        compiled_inputs: Mapping[str, Any],
        input_provenance: Mapping[str, str],
        now: str,
    ) -> dict[str, dict[str, Any]]:
        tenant = _text("tenant_id", tenant_id, 128)
        step_id = _uuid("executable_step_id", executable_step_id)
        artifact_ref = _ref("verified_artifact_ref", verified_artifact_ref)
        context = validate_context_projection(context_projection)
        observed = _timestamp("now", now)
        try:
            with self._session_factory() as session:
                lineage = _load_step_lineage(session, tenant, step_id)
                _require_local_skill_lineage(lineage)
                artifact = _load_artifact(session, tenant, artifact_ref)
                if artifact is None:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_artifact_not_found",
                        "NSL binding requires a persisted verified Skill artifact.",
                    )
                artifact = validate_verified_skill_artifact(artifact)
                _require_artifact_selector(lineage, artifact)
                backend_profile = _lineage_backend_profile(lineage)
                context_id = _require_agent_context(session, tenant, lineage, context)
                existing = _load_bundle(session, tenant, step_id)
                if existing is not None:
                    expected_request = _request_for(
                        lineage=lineage,
                        artifact=artifact,
                        context=context,
                        compiled_inputs=compiled_inputs,
                        input_provenance=input_provenance,
                        nsl_execution_id=existing["binding"]["nsl_execution_id"],
                        business_operation_id=existing["binding"][
                            "business_operation_id"
                        ],
                    )
                    _require_replay(
                        existing,
                        expected_request,
                        context,
                        artifact,
                        backend_profile,
                    )
                    return existing

                nsl_execution_id = _uuid("nsl_execution_id", self._id_factory())
                business_operation_id = _uuid(
                    "business_operation_id", self._id_factory()
                )
                request = _request_for(
                    lineage=lineage,
                    artifact=artifact,
                    context=context,
                    compiled_inputs=compiled_inputs,
                    input_provenance=input_provenance,
                    nsl_execution_id=nsl_execution_id,
                    business_operation_id=business_operation_id,
                )
                request_ref = f"AE:NSL_REQUEST:{nsl_execution_id}"
                binding = validate_nsl_step_execution_binding(
                    {
                        "schema_version": NSL_STEP_BINDING_SCHEMA_VERSION,
                        "tenant_id": tenant,
                        "agent_execution_id": lineage["agent_execution_id"],
                        "executable_plan_id": lineage["executable_plan_id"],
                        "executable_step_id": step_id,
                        "nsl_execution_id": nsl_execution_id,
                        "business_operation_id": business_operation_id,
                        "skill_id": artifact["skill_id"],
                        "exact_skill_version": artifact["skill_version"],
                        "skill_semantic_hash": artifact["skill_semantic_hash"],
                        "verified_artifact_ref": artifact["artifact_ref"],
                        "verified_artifact_hash": artifact["artifact_hash"],
                        "request_ref": request_ref,
                        "request_hash": semantic_sha256_hash_ref(request),
                        "backend_profile": backend_profile,
                        "state": "REQUEST_BOUND",
                        "result_summary_ref": None,
                        "result_summary_hash": None,
                        "allocated_at": observed,
                        "request_bound_at": observed,
                        "invocation_started_at": None,
                        "completed_at": None,
                        "created_at": observed,
                        "updated_at": observed,
                    }
                )
                params = _binding_params(binding, request, context, context_id)
                session.execute(text(_insert_sql(_dialect_name(session))), params)
                saved = _load_bundle(session, tenant, step_id)
                if saved is None:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_write_conflict",
                        "NSL step execution binding could not be reloaded.",
                        True,
                    )
                _require_replay(saved, request, context, artifact, backend_profile)
                session.commit()
                return saved
        except NSLStepExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise NSLStepExecutionError(
                "ae.nsl_binding_store_unavailable",
                "AE NSL step execution binding store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, executable_step_id: str
    ) -> dict[str, dict[str, Any]] | None:
        tenant = _text("tenant_id", tenant_id, 128)
        step_id = _uuid("executable_step_id", executable_step_id)
        try:
            with self._session_factory() as session:
                return _load_bundle(session, tenant, step_id)
        except SQLAlchemyError as exc:
            raise NSLStepExecutionError(
                "ae.nsl_binding_store_unavailable",
                "AE NSL step execution binding store is unavailable.",
                True,
            ) from exc

    def mark_invocation_started(
        self, *, tenant_id: str, executable_step_id: str, now: str
    ) -> dict[str, dict[str, Any]]:
        tenant = _text("tenant_id", tenant_id, 128)
        step_id = _uuid("executable_step_id", executable_step_id)
        observed = _timestamp("now", now)
        try:
            with self._session_factory() as session:
                existing = _load_bundle(session, tenant, step_id)
                if existing is None:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_not_found",
                        "NSL invocation requires a durable request binding.",
                    )
                binding = existing["binding"]
                if binding["state"] == "RUNNING":
                    return existing
                if binding["state"] != "REQUEST_BOUND":
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_state_conflict",
                        "NSL invocation cannot start from the current binding state.",
                    )
                running = validate_nsl_step_execution_binding(
                    {
                        **binding,
                        "state": "RUNNING",
                        "invocation_started_at": observed,
                        "updated_at": observed,
                    }
                )
                result = session.execute(
                    text(_mark_running_sql(_dialect_name(session))),
                    {
                        "tenant_id": tenant,
                        "step_id": step_id,
                        "request_hash": running["request_hash"],
                        "binding_json": canonical_json(running),
                        "now": observed,
                    },
                )
                if result.rowcount != 1:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_state_conflict",
                        "NSL invocation start lost its request-bound state.",
                        True,
                    )
                saved = _load_bundle(session, tenant, step_id)
                if saved is None or saved["binding"] != running:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_write_conflict",
                        "Running NSL binding could not be reloaded.",
                        True,
                    )
                session.commit()
                return saved
        except NSLStepExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise NSLStepExecutionError(
                "ae.nsl_binding_store_unavailable",
                "AE NSL step execution binding store is unavailable.",
                True,
            ) from exc

    def mark_result_terminal(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        state: str,
        result_summary_ref: str,
        result_summary_hash: str,
        completed_at: str,
    ) -> dict[str, dict[str, Any]]:
        tenant = _text("tenant_id", tenant_id, 128)
        step_id = _uuid("executable_step_id", executable_step_id)
        if state not in _TERMINAL_STATES:
            raise _invalid("NSL result terminal state is invalid.")
        summary_ref = _ref("result_summary_ref", result_summary_ref)
        summary_hash = _hash("result_summary_hash", result_summary_hash)
        completed = _timestamp("completed_at", completed_at)
        try:
            with self._session_factory() as session:
                existing = _load_bundle(session, tenant, step_id)
                if existing is None:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_not_found",
                        "NSL result requires a durable request binding.",
                    )
                binding = existing["binding"]
                if binding["state"] in _TERMINAL_STATES:
                    expected = {
                        "state": state,
                        "result_summary_ref": summary_ref,
                        "result_summary_hash": summary_hash,
                        "completed_at": completed,
                    }
                    if any(binding[key] != value for key, value in expected.items()):
                        raise NSLStepExecutionError(
                            "ae.nsl_binding_terminal_conflict",
                            "NSL binding already has different terminal evidence.",
                        )
                    return existing
                if binding["state"] != "RUNNING":
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_state_conflict",
                        "NSL result cannot terminalize the current binding state.",
                    )
                terminal = validate_nsl_step_execution_binding(
                    {
                        **binding,
                        "state": state,
                        "result_summary_ref": summary_ref,
                        "result_summary_hash": summary_hash,
                        "completed_at": completed,
                        "updated_at": completed,
                    }
                )
                result = session.execute(
                    text(_mark_terminal_sql(_dialect_name(session))),
                    {
                        "tenant_id": tenant,
                        "step_id": step_id,
                        "request_hash": terminal["request_hash"],
                        "state": state,
                        "binding_json": canonical_json(terminal),
                        "completed_at": completed,
                    },
                )
                if result.rowcount != 1:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_terminal_conflict",
                        "NSL binding state changed before terminal evidence was stored.",
                        True,
                    )
                saved = _load_bundle(session, tenant, step_id)
                if saved is None or saved["binding"] != terminal:
                    raise NSLStepExecutionError(
                        "ae.nsl_binding_write_conflict",
                        "Terminal NSL binding could not be reloaded.",
                        True,
                    )
                session.commit()
                return saved
        except NSLStepExecutionError:
            raise
        except SQLAlchemyError as exc:
            raise NSLStepExecutionError(
                "ae.nsl_binding_store_unavailable",
                "AE NSL step execution binding store is unavailable.",
                True,
            ) from exc


def nsl_step_execution_table_sql(dialect_name: str) -> tuple[str, ...]:
    json_type = "TEXT" if dialect_name == "sqlite" else "JSONB"
    timestamp_type = "TEXT" if dialect_name == "sqlite" else "TIMESTAMPTZ"
    return (
        f"""
        CREATE TABLE ae_nsl_step_execution (
            tenant_id TEXT NOT NULL,
            executable_step_id TEXT NOT NULL,
            agent_execution_id TEXT NOT NULL,
            executable_plan_id TEXT NOT NULL,
            agent_context_id TEXT NOT NULL,
            nsl_execution_id TEXT NOT NULL,
            business_operation_id TEXT NOT NULL,
            verified_artifact_ref TEXT NOT NULL,
            verified_artifact_hash TEXT NOT NULL,
            request_ref TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            backend_profile TEXT NOT NULL,
            state TEXT NOT NULL,
            binding_json {json_type} NOT NULL,
            request_json {json_type} NOT NULL,
            context_projection_json {json_type} NOT NULL,
            allocated_at {timestamp_type} NOT NULL,
            request_bound_at {timestamp_type},
            invocation_started_at {timestamp_type},
            completed_at {timestamp_type},
            created_at {timestamp_type} NOT NULL,
            updated_at {timestamp_type} NOT NULL,
            PRIMARY KEY (tenant_id, executable_step_id),
            UNIQUE (tenant_id, nsl_execution_id),
            UNIQUE (tenant_id, business_operation_id),
            UNIQUE (tenant_id, request_ref)
        )
        """,
        "CREATE INDEX idx_ae_nsl_step_state ON ae_nsl_step_execution (tenant_id, state, updated_at)",
    )


def _request_for(**kwargs: Any) -> dict[str, Any]:
    lineage = kwargs.pop("lineage")
    context = kwargs.pop("context")
    return build_skill_execution_request(
        tenant_id=lineage["tenant_id"],
        agent_execution_id=lineage["agent_execution_id"],
        executable_plan_id=lineage["executable_plan_id"],
        executable_step_id=lineage["executable_step_id"],
        context_projection_ref=f"AE:NSL_CONTEXT_PROJECTION:{lineage['executable_step_id']}",
        correlation_id=lineage["correlation_id"],
        causation_id=lineage["causation_id"],
        context_projection=context,
        **kwargs,
    )


def _load_step_lineage(
    session: Session, tenant_id: str, step_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT tenant_id, executable_step_id, agent_execution_id, executable_plan_id, "
                "step_type, executor_kind, required_capability, capability_version, "
                "skill_binding_json, "
                "correlation_id, causation_id FROM ae_executable_step "
                "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
            ),
            {"tenant_id": tenant_id, "step_id": step_id},
        )
        .mappings()
        .first()
    )
    return (
        None
        if row is None
        else {
            **{
                key: (
                    str(value) if key.endswith("_id") and value is not None else value
                )
                for key, value in row.items()
                if key != "skill_binding_json"
            },
            "skill_binding": (
                None
                if row["skill_binding_json"] is None
                else _json_object("LOCAL_SKILL binding", row["skill_binding_json"])
            ),
        }
    )


def _require_local_skill_lineage(lineage: Mapping[str, Any] | None) -> None:
    if lineage is None:
        raise NSLStepExecutionError(
            "ae.nsl_binding_step_not_found",
            "NSL binding requires an existing ExecutableStep.",
        )
    if lineage["executable_plan_id"] is None or lineage["step_type"] != "LOCAL_SKILL":
        raise _invalid("NSL binding requires a planned LOCAL_SKILL step.")
    if lineage["executor_kind"] not in {"LOCAL_SKILL_UNAVAILABLE", "LOCAL_SKILL"}:
        raise _invalid("NSL binding cannot target a non-local-Skill executor.")


def _load_artifact(
    session: Session, tenant_id: str, artifact_ref: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT artifact_json FROM ae_nsl_artifact WHERE tenant_id = :tenant_id AND artifact_ref = :artifact_ref"
            ),
            {"tenant_id": tenant_id, "artifact_ref": artifact_ref},
        )
        .mappings()
        .first()
    )
    return (
        None
        if row is None
        else _json_object("VerifiedSkillArtifact", row["artifact_json"])
    )


def _require_artifact_selector(
    lineage: Mapping[str, Any], artifact: Mapping[str, Any]
) -> None:
    if lineage["executor_kind"] != "LOCAL_SKILL":
        if (
            lineage["required_capability"] != artifact["skill_id"]
            or lineage["capability_version"] != artifact["skill_version"]
        ):
            raise NSLStepExecutionError(
                "ae.nsl_binding_artifact_mismatch",
                "Verified Skill artifact does not match the exact compiled step selector.",
            )
        return
    try:
        binding = validate_local_skill_binding(lineage["skill_binding"])
    except Exception as exc:
        raise _invalid(
            "Active LOCAL_SKILL step lacks its exact compiled binding."
        ) from exc
    if (
        binding.get("capability_id", binding["skill_id"])
        != lineage["required_capability"]
        or binding["exact_skill_version"] != lineage["capability_version"]
    ):
        raise NSLStepExecutionError(
            "ae.nsl_binding_artifact_mismatch",
            "LOCAL_SKILL binding does not match the exact compiled capability selector.",
        )
    if (
        binding["skill_id"] != artifact["skill_id"]
        or binding["exact_skill_version"] != artifact["skill_version"]
    ):
        raise NSLStepExecutionError(
            "ae.nsl_binding_artifact_mismatch",
            "Verified Skill artifact does not match the exact compiled Skill selector.",
        )
    if (
        binding["skill_semantic_hash"] != artifact["skill_semantic_hash"]
        or binding["runtime_contract_ref"] != artifact["runtime_contract_ref"]
        or binding["trust_policy_id"] != artifact["trust_evidence"]["trust_policy_id"]
    ):
        raise NSLStepExecutionError(
            "ae.nsl_binding_artifact_mismatch",
            "Verified Skill artifact does not match the compiled runtime binding.",
        )


def _lineage_backend_profile(lineage: Mapping[str, Any]) -> str:
    if lineage["executor_kind"] != "LOCAL_SKILL":
        return NSL_V01_PROCESS_ISOLATED_BACKEND
    try:
        binding = validate_local_skill_binding(lineage["skill_binding"])
    except Exception as exc:
        raise _invalid(
            "Active LOCAL_SKILL step lacks its exact compiled binding."
        ) from exc
    return binding["backend_profile"]


def _require_agent_context(
    session: Session,
    tenant_id: str,
    lineage: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> str:
    row = (
        session.execute(
            text(
                "SELECT context_id, context_generation, context_hash FROM ae_agent_context "
                "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id "
                "ORDER BY context_generation DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "execution_id": lineage["agent_execution_id"]},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NSLStepExecutionError(
            "ae.nsl_binding_context_not_found",
            "NSL binding requires persisted AgentContext lineage.",
        )
    context_id = str(row["context_id"])
    expected_ref = f"AE:AGENT_CONTEXT:{context_id}:{int(row['context_generation'])}"
    if (
        projection["agent_context_ref"] != expected_ref
        or projection["agent_context_hash"] != row["context_hash"]
        or projection["verified_principal"]["tenant_id"] != tenant_id
    ):
        raise NSLStepExecutionError(
            "ae.nsl_binding_context_mismatch",
            "Bounded context projection does not match trusted AgentContext lineage.",
        )
    return context_id


def _binding_params(
    binding: Mapping[str, Any],
    request: Mapping[str, Any],
    context: Mapping[str, Any],
    context_id: str,
) -> dict[str, Any]:
    return {
        "tenant_id": binding["tenant_id"],
        "executable_step_id": binding["executable_step_id"],
        "agent_execution_id": binding["agent_execution_id"],
        "executable_plan_id": binding["executable_plan_id"],
        "agent_context_id": context_id,
        "nsl_execution_id": binding["nsl_execution_id"],
        "business_operation_id": binding["business_operation_id"],
        "verified_artifact_ref": binding["verified_artifact_ref"],
        "verified_artifact_hash": binding["verified_artifact_hash"],
        "request_ref": binding["request_ref"],
        "request_hash": binding["request_hash"],
        "backend_profile": binding["backend_profile"],
        "state": binding["state"],
        "binding_json": canonical_json(binding),
        "request_json": canonical_json(request),
        "context_projection_json": canonical_json(context),
        "allocated_at": binding["allocated_at"],
        "request_bound_at": binding["request_bound_at"],
        "invocation_started_at": binding["invocation_started_at"],
        "completed_at": binding["completed_at"],
        "created_at": binding["created_at"],
        "updated_at": binding["updated_at"],
    }


def _insert_sql(dialect_name: str) -> str:
    json_value = "CAST(:{name} AS JSONB)" if dialect_name == "postgresql" else ":{name}"
    return """
        INSERT INTO ae_nsl_step_execution (
            tenant_id, executable_step_id, agent_execution_id, executable_plan_id,
            agent_context_id, nsl_execution_id, business_operation_id,
            verified_artifact_ref, verified_artifact_hash, request_ref, request_hash,
            backend_profile, state, binding_json, request_json,
            context_projection_json, allocated_at, request_bound_at,
            invocation_started_at, completed_at, created_at, updated_at
        ) VALUES (
            :tenant_id, :executable_step_id, :agent_execution_id, :executable_plan_id,
            :agent_context_id, :nsl_execution_id, :business_operation_id,
            :verified_artifact_ref, :verified_artifact_hash, :request_ref, :request_hash,
            :backend_profile, :state, {binding_json}, {request_json}, {context_json},
            :allocated_at, :request_bound_at, :invocation_started_at, :completed_at,
            :created_at, :updated_at
        ) ON CONFLICT DO NOTHING
    """.format(
        binding_json=json_value.format(name="binding_json"),
        request_json=json_value.format(name="request_json"),
        context_json=json_value.format(name="context_projection_json"),
    )


def _mark_running_sql(dialect_name: str) -> str:
    binding_json = (
        "CAST(:binding_json AS JSONB)"
        if dialect_name == "postgresql"
        else ":binding_json"
    )
    return f"""
        UPDATE ae_nsl_step_execution
        SET state = 'RUNNING', binding_json = {binding_json},
            invocation_started_at = :now, updated_at = :now
        WHERE tenant_id = :tenant_id AND executable_step_id = :step_id
          AND state = 'REQUEST_BOUND' AND request_hash = :request_hash
    """


def _mark_terminal_sql(dialect_name: str) -> str:
    binding_json = (
        "CAST(:binding_json AS JSONB)"
        if dialect_name == "postgresql"
        else ":binding_json"
    )
    return f"""
        UPDATE ae_nsl_step_execution
        SET state = :state, binding_json = {binding_json},
            completed_at = :completed_at, updated_at = :completed_at
        WHERE tenant_id = :tenant_id AND executable_step_id = :step_id
          AND state = 'RUNNING' AND request_hash = :request_hash
    """


def _load_bundle(
    session: Session, tenant_id: str, step_id: str
) -> dict[str, dict[str, Any]] | None:
    row = (
        session.execute(
            text(
                "SELECT binding_json, request_json, context_projection_json "
                "FROM ae_nsl_step_execution WHERE tenant_id = :tenant_id "
                "AND executable_step_id = :step_id"
            ),
            {"tenant_id": tenant_id, "step_id": step_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "binding": validate_nsl_step_execution_binding(
            _json_object("binding", row["binding_json"])
        ),
        "request": validate_skill_execution_request(
            _json_object("request", row["request_json"])
        ),
        "context_projection": validate_context_projection(
            _json_object("context projection", row["context_projection_json"])
        ),
    }


def _require_replay(
    saved: Mapping[str, Mapping[str, Any]],
    request: Mapping[str, Any],
    context: Mapping[str, Any],
    artifact: Mapping[str, Any],
    backend_profile: str,
) -> None:
    binding = saved["binding"]
    conflicts = tuple(
        name
        for name, differs in (
            ("request", saved["request"] != request),
            ("context", saved["context_projection"] != context),
            (
                "request_hash",
                binding["request_hash"] != semantic_sha256_hash_ref(request),
            ),
            (
                "artifact_ref",
                binding["verified_artifact_ref"] != artifact["artifact_ref"],
            ),
            (
                "artifact_hash",
                binding["verified_artifact_hash"] != artifact["artifact_hash"],
            ),
            ("backend_profile", binding["backend_profile"] != backend_profile),
        )
        if differs
    )
    if conflicts:
        raise NSLStepExecutionError(
            "ae.nsl_binding_immutable_conflict",
            "ExecutableStep already has a different immutable NSL request binding "
            f"({', '.join(conflicts)}).",
        )


def _canonical_mapping(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be an object.")
    try:
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be canonical JSON.") from exc


def _json_object(name: str, value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise _invalid(f"Stored {name} is not an object.")
    return dict(decoded)


def _reject_private_material(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_KEYS:
                raise _invalid("Request/context projection contains private material.")
            _reject_private_material(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private_material(item)


def _refs(field: str, value: object, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise _invalid(f"{field} must be a bounded reference array.")
    refs = [_ref(field, item) for item in value]
    if len(set(refs)) != len(refs):
        raise _invalid(f"{field} contains duplicate references.")
    return sorted(refs)


def _text_list(field: str, value: object, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise _invalid(f"{field} must be a bounded text array.")
    items = [_text(field, item, 256) for item in value]
    if len(set(items)) != len(items):
        raise _invalid(f"{field} contains duplicate values.")
    return items


def _uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference.") from exc


def _optional_hash(field: str, value: object) -> str | None:
    return None if value is None else _hash(field, value)


def _selector(field: str, value: object) -> str:
    if not isinstance(value, str) or _SELECTOR.fullmatch(value) is None:
        raise _invalid(f"{field} must be a bounded ASCII selector.")
    return value


def _ref(field: str, value: object) -> str:
    return _text(field, value, 512)


def _optional_ref(field: str, value: object) -> str | None:
    return None if value is None else _ref(field, value)


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _text(field, value, maximum)


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _invalid(f"{field} is outside its supported range.")
    return value


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be an RFC 3339 date-time string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 date-time string.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_timestamp(field: str, value: object) -> str | None:
    return None if value is None else _timestamp(field, value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> NSLStepExecutionError:
    return NSLStepExecutionError("ae.nsl_binding_invalid", detail)
