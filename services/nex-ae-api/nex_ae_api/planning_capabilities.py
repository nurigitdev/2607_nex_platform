from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

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
    NSL_V01_BACKEND_PROFILES,
    normalize_nsl_backend_profile_for_operation,
)

CAPABILITY_SNAPSHOT_SCHEMA_VERSION = "1.1"
P6_CAPABILITY_SNAPSHOT_SCHEMA_VERSION = "1.2"
CAPABILITY_VERSION = "p5.1"
CHAT_CAPABILITY_ID = "AE.CHAT.COMPATIBILITY"
REPORT_CAPABILITY_ID = "AE.RESULT.REPORT"
LOCAL_SKILL_EXECUTOR_KIND = "LOCAL_SKILL"
LOCAL_SKILL_STEP_TYPE = "LOCAL_SKILL"
LOCAL_SKILL_BACKEND_PROFILE = DEFAULT_NSL_V01_BACKEND_PROFILE
LOCAL_SKILL_BACKEND_PROFILES = NSL_V01_BACKEND_PROFILES
LOCAL_SKILL_PACKAGE_REQUIREMENT = "SIGNED_TRUSTED_ACTIVE"
_CAPABILITY_ID = re.compile(r"^[A-Z][A-Z0-9_]*(\.[A-Z][A-Z0-9_]*)+$")
_SELECTOR = re.compile(r"^[\x21-\x7e]{1,256}$")

DEFAULT_P5_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "capability_id": CHAT_CAPABILITY_ID,
        "capability_version": CAPABILITY_VERSION,
        "status": "ACTIVE",
        "allowed_logical_step_types": ["LOCAL_CAPABILITY"],
        "executable_step_type": "CANONICAL_CAPABILITY",
        "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
        "input_contract_ref": "contract://nex/ae/chat-request/v1",
        "output_contract_ref": "contract://nex/ae/chat-result/v1",
        "operation_semantics": "GENERATE",
    },
    {
        "capability_id": REPORT_CAPABILITY_ID,
        "capability_version": CAPABILITY_VERSION,
        "status": "ACTIVE",
        "allowed_logical_step_types": ["REPORT"],
        "executable_step_type": "REPORT",
        "executor_kind": "DETERMINISTIC_REPORT",
        "input_contract_ref": "contract://nex/ae/step-result/v1",
        "output_contract_ref": "contract://nex/ae/interactive-response/v1",
        "operation_semantics": "REPORT",
    },
)


@dataclass(frozen=True)
class CapabilitySnapshotError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_capability_snapshot(
    *,
    tenant_id: str,
    capability_snapshot_id: str,
    snapshot_version: int,
    created_at: str,
    capabilities: Sequence[Mapping[str, Any]] = DEFAULT_P5_CAPABILITIES,
) -> dict[str, Any]:
    normalized = [_validate_capability(item) for item in capabilities]
    if not normalized:
        raise _invalid("Capability snapshot must contain at least one capability.")
    if len(normalized) > 64:
        raise _invalid("Capability snapshot cannot exceed 64 capabilities.")
    identities = [
        (item["capability_id"], item["capability_version"]) for item in normalized
    ]
    if len(set(identities)) != len(identities):
        raise _invalid("Capability snapshot contains duplicate exact versions.")
    schema_version = (
        P6_CAPABILITY_SNAPSHOT_SCHEMA_VERSION
        if any(
            item["executor_kind"] == LOCAL_SKILL_EXECUTOR_KIND for item in normalized
        )
        else CAPABILITY_SNAPSHOT_SCHEMA_VERSION
    )
    snapshot: dict[str, Any] = {
        "schema_version": schema_version,
        "tenant_id": _required_text("tenant_id", tenant_id, 128),
        "capability_snapshot_id": _required_uuid(
            "capability_snapshot_id", capability_snapshot_id
        ),
        "snapshot_version": _bounded_int("snapshot_version", snapshot_version, 1, 9999),
        "capabilities": sorted(
            normalized,
            key=lambda item: (item["capability_id"], item["capability_version"]),
        ),
        "created_at": _required_datetime("created_at", created_at),
    }
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)
    return snapshot


def build_local_skill_capability(
    *,
    skill_id: str,
    capability_id: str | None = None,
    exact_skill_version: str,
    skill_semantic_hash: str,
    input_contract_ref: str,
    output_contract_ref: str,
    runtime_contract_ref: str,
    trust_policy_id: str,
    backend_profile: str = LOCAL_SKILL_BACKEND_PROFILE,
    operation_semantics: str = "READ",
) -> dict[str, Any]:
    """Build one exact P6/P8 LOCAL_SKILL capability descriptor."""
    resolved_capability_id = capability_id or skill_id
    capability = {
        "capability_id": resolved_capability_id,
        "capability_version": exact_skill_version,
        "status": "ACTIVE",
        "allowed_logical_step_types": ["LOCAL_CAPABILITY"],
        "executable_step_type": LOCAL_SKILL_STEP_TYPE,
        "executor_kind": LOCAL_SKILL_EXECUTOR_KIND,
        "input_contract_ref": input_contract_ref,
        "output_contract_ref": output_contract_ref,
        "operation_semantics": operation_semantics,
        "local_skill_binding": {
            "skill_id": skill_id,
            "exact_skill_version": exact_skill_version,
            "skill_semantic_hash": skill_semantic_hash,
            "runtime_contract_ref": runtime_contract_ref,
            "trust_policy_id": trust_policy_id,
            "backend_profile": backend_profile,
            "package_requirement": LOCAL_SKILL_PACKAGE_REQUIREMENT,
            **(
                {"capability_id": resolved_capability_id}
                if resolved_capability_id != skill_id
                else {}
            ),
        },
    }
    return _validate_capability(capability)


def capability_by_exact_version(
    snapshot: Mapping[str, Any], capability_id: str, capability_version: str
) -> dict[str, Any]:
    normalized = _validate_snapshot(snapshot)
    matches = [
        item
        for item in normalized["capabilities"]
        if item["capability_id"] == capability_id
        and item["capability_version"] == capability_version
    ]
    if len(matches) != 1:
        raise CapabilitySnapshotError(
            "ae.capability_exact_version_unavailable",
            "The exact capability version is unavailable.",
        )
    return matches[0]


class SqlAlchemyCapabilitySnapshotRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _validate_snapshot(snapshot)
        params = {
            "tenant_id": normalized["tenant_id"],
            "capability_snapshot_id": normalized["capability_snapshot_id"],
            "snapshot_version": normalized["snapshot_version"],
            "snapshot_hash": normalized["snapshot_hash"],
            "snapshot_json": canonical_json(normalized),
            "created_at": normalized["created_at"],
        }
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_snapshot_insert_sql(_dialect_name(session))), params
                )
                saved = _load_snapshot(
                    session,
                    normalized["tenant_id"],
                    normalized["capability_snapshot_id"],
                )
                if saved is None:
                    conflict = _load_snapshot_by_version(
                        session,
                        normalized["tenant_id"],
                        normalized["snapshot_version"],
                    )
                    if conflict is not None:
                        raise CapabilitySnapshotError(
                            "ae.capability_snapshot_version_conflict",
                            "A different snapshot owns this tenant version.",
                        )
                    raise CapabilitySnapshotError(
                        "ae.capability_snapshot_write_conflict",
                        "Capability snapshot could not be reloaded.",
                        True,
                    )
                if saved != normalized:
                    raise CapabilitySnapshotError(
                        "ae.capability_snapshot_immutable_conflict",
                        "Capability snapshot identity exists with different content.",
                    )
                session.commit()
                return saved
        except CapabilitySnapshotError:
            raise
        except SQLAlchemyError as exc:
            raise CapabilitySnapshotError(
                "ae.capability_snapshot_store_unavailable",
                "AE capability snapshot store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, capability_snapshot_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        capability_snapshot_id = _required_uuid(
            "capability_snapshot_id", capability_snapshot_id
        )
        try:
            with self._session_factory() as session:
                return _load_snapshot(session, tenant_id, capability_snapshot_id)
        except SQLAlchemyError as exc:
            raise CapabilitySnapshotError(
                "ae.capability_snapshot_store_unavailable",
                "AE capability snapshot store is unavailable.",
                True,
            ) from exc

    def get_latest(self, *, tenant_id: str) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            "SELECT snapshot_json FROM ae_capability_snapshot "
                            "WHERE tenant_id = :tenant_id "
                            "ORDER BY snapshot_version DESC, created_at DESC LIMIT 1"
                        ),
                        {"tenant_id": tenant_id},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    return None
                return _validate_snapshot(_json_value(row["snapshot_json"]))
        except CapabilitySnapshotError:
            raise
        except SQLAlchemyError as exc:
            raise CapabilitySnapshotError(
                "ae.capability_snapshot_store_unavailable",
                "AE capability snapshot store is unavailable.",
                True,
            ) from exc


def validate_capability_snapshot_contract(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    return _validate_snapshot(value)


def validate_capability_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one capability descriptor without manufacturing a snapshot."""

    return _validate_capability(value)


def _validate_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("Capability snapshot must be canonical JSON.") from exc
    if set(record) != {
        "schema_version",
        "tenant_id",
        "capability_snapshot_id",
        "snapshot_version",
        "capabilities",
        "snapshot_hash",
        "created_at",
    }:
        raise _invalid("Capability snapshot fields do not match v1.1.")
    schema_version = record["schema_version"]
    if schema_version not in {
        CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
        P6_CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
    }:
        raise _invalid("Capability snapshot schema_version must be 1.1 or 1.2.")
    _required_text("tenant_id", record["tenant_id"], 128)
    _required_uuid("capability_snapshot_id", record["capability_snapshot_id"])
    _bounded_int("snapshot_version", record["snapshot_version"], 1, 9999)
    if (
        not isinstance(record["capabilities"], list)
        or not 1 <= len(record["capabilities"]) <= 64
    ):
        raise _invalid("Capability snapshot capabilities must contain 1..64 items.")
    normalized = [_validate_capability(item) for item in record["capabilities"]]
    has_local_skill = any(
        item["executor_kind"] == LOCAL_SKILL_EXECUTOR_KIND for item in normalized
    )
    if has_local_skill != (schema_version == P6_CAPABILITY_SNAPSHOT_SCHEMA_VERSION):
        raise _invalid(
            "Capability snapshot version does not match LOCAL_SKILL content."
        )
    identities = [
        (item["capability_id"], item["capability_version"]) for item in normalized
    ]
    if len(set(identities)) != len(identities):
        raise _invalid("Capability snapshot contains duplicate exact versions.")
    if normalized != sorted(
        normalized,
        key=lambda item: (item["capability_id"], item["capability_version"]),
    ):
        raise _invalid("Capability snapshot capabilities must be canonically ordered.")
    _required_datetime("created_at", record["created_at"])
    try:
        validate_hash_ref(record["snapshot_hash"])
    except ValueError as exc:
        raise _invalid("Capability snapshot hash is invalid.") from exc
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "snapshot_hash"}
    )
    if record["snapshot_hash"] != expected:
        raise _invalid("Capability snapshot hash does not match its content.")
    return record


def _validate_capability(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "capability_id",
        "capability_version",
        "status",
        "allowed_logical_step_types",
        "executable_step_type",
        "executor_kind",
        "input_contract_ref",
        "output_contract_ref",
        "operation_semantics",
    }
    if not isinstance(value, Mapping) or not fields.issubset(value):
        raise _invalid("Capability fields do not match v1.1.")
    has_local_binding = "local_skill_binding" in value
    if set(value) != fields | ({"local_skill_binding"} if has_local_binding else set()):
        raise _invalid("Capability fields do not match a supported contract.")
    capability_id = _required_text("capability_id", value["capability_id"], 160)
    if _CAPABILITY_ID.fullmatch(capability_id) is None:
        raise _invalid("Capability ID is invalid.")
    step_types = value["allowed_logical_step_types"]
    if (
        not isinstance(step_types, list | tuple)
        or not step_types
        or any(
            item not in {"LOCAL_CAPABILITY", "AGGREGATE", "REPORT"}
            for item in step_types
        )
        or len(set(step_types)) != len(step_types)
    ):
        raise _invalid("Capability logical step types are invalid.")
    executable_type = value["executable_step_type"]
    if executable_type not in {
        "CANONICAL_CAPABILITY",
        "AGGREGATE",
        "REPORT",
        LOCAL_SKILL_STEP_TYPE,
    }:
        raise _invalid("Capability executable step type is invalid.")
    executor_kind = value["executor_kind"]
    if executor_kind not in {
        "P4_CHAT_RAG_COMPATIBILITY",
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        LOCAL_SKILL_EXECUTOR_KIND,
    }:
        raise _invalid("Capability executor kind is invalid.")
    semantics = value["operation_semantics"]
    if semantics not in {"READ", "WRITE", "GENERATE", "AGGREGATE", "REPORT"}:
        raise _invalid("Capability operation semantics are invalid.")
    if value["status"] != "ACTIVE":
        raise _invalid("Capability status must be ACTIVE.")
    normalized = {
        "capability_id": capability_id,
        "capability_version": _required_text(
            "capability_version", value["capability_version"], 64
        ),
        "status": "ACTIVE",
        "allowed_logical_step_types": list(step_types),
        "executable_step_type": executable_type,
        "executor_kind": executor_kind,
        "input_contract_ref": _required_text(
            "input_contract_ref", value["input_contract_ref"], 256
        ),
        "output_contract_ref": _required_text(
            "output_contract_ref", value["output_contract_ref"], 256
        ),
        "operation_semantics": semantics,
    }
    if executor_kind == LOCAL_SKILL_EXECUTOR_KIND:
        if not has_local_binding:
            raise _invalid("LOCAL_SKILL capability requires an exact Skill binding.")
        if executable_type != LOCAL_SKILL_STEP_TYPE or semantics not in {
            "READ",
            "WRITE",
        }:
            raise _invalid(
                "LOCAL_SKILL capability must use READ or WRITE operation semantics."
            )
        binding = validate_local_skill_binding(
            value["local_skill_binding"], operation_semantics=semantics
        )
        bound_capability_id = binding.get("capability_id", binding["skill_id"])
        if (
            bound_capability_id != capability_id
            or binding["exact_skill_version"] != normalized["capability_version"]
        ):
            raise _invalid(
                "LOCAL_SKILL capability and Skill selector must match exactly."
            )
        normalized["local_skill_binding"] = binding
    elif semantics == "WRITE":
        raise _invalid("WRITE capability must use an exact LOCAL_SKILL binding.")
    elif has_local_binding or executable_type == LOCAL_SKILL_STEP_TYPE:
        raise _invalid("Only LOCAL_SKILL may carry an exact Skill binding.")
    return normalized


def validate_local_skill_binding(
    value: object, *, operation_semantics: str = "READ"
) -> dict[str, str]:
    fields = {
        "skill_id",
        "exact_skill_version",
        "skill_semantic_hash",
        "runtime_contract_ref",
        "trust_policy_id",
        "backend_profile",
        "package_requirement",
    }
    optional_fields = {"capability_id"}
    if (
        not isinstance(value, Mapping)
        or not fields.issubset(value)
        or not set(value).issubset(fields | optional_fields)
    ):
        raise _invalid("LOCAL_SKILL binding fields are invalid.")
    skill_id = _required_text("skill_id", value["skill_id"], 160)
    if _CAPABILITY_ID.fullmatch(skill_id) is None:
        raise _invalid("LOCAL_SKILL skill_id is invalid.")
    exact_version = _required_text(
        "exact_skill_version", value["exact_skill_version"], 64
    )
    if _SELECTOR.fullmatch(exact_version) is None:
        raise _invalid("LOCAL_SKILL exact version is invalid.")
    try:
        semantic_hash = validate_hash_ref(value["skill_semantic_hash"])
    except ValueError as exc:
        raise _invalid("LOCAL_SKILL semantic hash is invalid.") from exc
    backend_profile = _required_text("backend_profile", value["backend_profile"], 128)
    try:
        backend_profile = normalize_nsl_backend_profile_for_operation(
            backend_profile, operation_semantics
        )
    except ValueError as exc:
        raise _invalid(
            "LOCAL_SKILL backend profile is unsupported for its operation semantics."
        ) from exc
    if value["package_requirement"] != LOCAL_SKILL_PACKAGE_REQUIREMENT:
        raise _invalid("LOCAL_SKILL package requirement must fail closed.")
    normalized = {
        "skill_id": skill_id,
        "exact_skill_version": exact_version,
        "skill_semantic_hash": semantic_hash,
        "runtime_contract_ref": _required_text(
            "runtime_contract_ref", value["runtime_contract_ref"], 256
        ),
        "trust_policy_id": _required_text(
            "trust_policy_id", value["trust_policy_id"], 256
        ),
        "backend_profile": backend_profile,
        "package_requirement": LOCAL_SKILL_PACKAGE_REQUIREMENT,
    }
    if "capability_id" in value:
        capability_id = _required_text("capability_id", value["capability_id"], 160)
        if _CAPABILITY_ID.fullmatch(capability_id) is None:
            raise _invalid("LOCAL_SKILL bound capability ID is invalid.")
        normalized["capability_id"] = capability_id
    return normalized


def _snapshot_insert_sql(dialect_name: str) -> str:
    snapshot_json = (
        "CAST(:snapshot_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":snapshot_json"
    )
    return f"""
        INSERT INTO ae_capability_snapshot (
            tenant_id, capability_snapshot_id, snapshot_version,
            snapshot_hash, snapshot_json, created_at
        ) VALUES (
            :tenant_id, :capability_snapshot_id, :snapshot_version,
            :snapshot_hash, {snapshot_json}, :created_at
        ) ON CONFLICT DO NOTHING
    """


def _load_snapshot(
    session: Session, tenant_id: str, snapshot_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("""
            SELECT snapshot_json FROM ae_capability_snapshot
            WHERE tenant_id = :tenant_id
              AND capability_snapshot_id = :snapshot_id
            """),
            {"tenant_id": tenant_id, "snapshot_id": snapshot_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_value(row["snapshot_json"])


def _load_snapshot_by_version(
    session: Session, tenant_id: str, version: int
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("""
            SELECT snapshot_json FROM ae_capability_snapshot
            WHERE tenant_id = :tenant_id AND snapshot_version = :version
            """),
            {"tenant_id": tenant_id, "version": version},
        )
        .mappings()
        .first()
    )
    return None if row is None else _json_value(row["snapshot_json"])


def _required_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(
            f"{field} must be a non-empty string up to {maximum} characters."
        )
    return value.strip()


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _invalid(f"{field} must be between {minimum} and {maximum}.")
    return value


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


def _json_value(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> CapabilitySnapshotError:
    return CapabilitySnapshotError("ae.capability_snapshot_invalid", detail)
