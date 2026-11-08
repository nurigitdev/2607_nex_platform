from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    sha256_from_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

VERIFIED_SKILL_ARTIFACT_SCHEMA_VERSION = "1.0"
PRODUCTION_ENVIRONMENTS = frozenset({"production", "staging"})
_SELECTOR = re.compile(r"^[\x21-\x7e]{1,256}$")


@dataclass(frozen=True)
class SkillArtifactGatewayError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class VerifiedPackageSkillResolver(Protocol):
    """Structural port matching nsl.api.VerifiedPackageSkillResolver."""

    def resolve(self, *, skill_id: str, skill_version: str) -> object: ...


class SkillArtifactAdmissionSource(Protocol):
    def current_admission(
        self,
        *,
        tenant_id: str,
        package_id: str,
        package_hash: str,
        signing_key_id: str,
        trust_policy_id: str,
        observed_at: str,
    ) -> Mapping[str, Any] | None: ...


class SkillArtifactRepository(Protocol):
    def save(
        self, *, tenant_id: str, artifact: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def get(
        self, *, tenant_id: str, artifact_ref: str
    ) -> dict[str, Any] | None: ...


class SkillArtifactGateway:
    def __init__(
        self,
        *,
        resolver: VerifiedPackageSkillResolver,
        admission_source: SkillArtifactAdmissionSource,
        repository: SkillArtifactRepository,
    ) -> None:
        self._resolver = resolver
        self._admission_source = admission_source
        self._repository = repository

    def resolve_verified(
        self,
        *,
        tenant_id: str,
        skill_id: str,
        exact_version: str,
        expected_semantic_hash: str,
        runtime_contract_ref: str,
        trust_policy_id: str,
        environment: str = "production",
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        tenant = _bounded_text("tenant_id", tenant_id, 128)
        requested_skill = _selector("skill_id", skill_id)
        requested_version = _selector("exact_version", exact_version)
        expected_hash = _hash_ref("expected_semantic_hash", expected_semantic_hash)
        contract_ref = _ref("runtime_contract_ref", runtime_contract_ref)
        policy_id = _bounded_text("trust_policy_id", trust_policy_id, 256)
        profile = _environment(environment)
        observed = _timestamp(
            "observed_at", observed_at or datetime.now(UTC).isoformat()
        )

        try:
            resolved = self._resolver.resolve(
                skill_id=requested_skill, skill_version=requested_version
            )
        except SkillArtifactGatewayError:
            raise
        except Exception as exc:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_resolution_failed",
                "Exact verified Skill package resolution failed.",
            ) from exc

        resolution = _resolved_projection(resolved)
        if (
            resolution["skill_id"] != requested_skill
            or resolution["skill_version"] != requested_version
        ):
            raise _rejected("Verified Skill resolver returned a different selector.")
        if resolution["skill_semantic_hash"] != expected_hash:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_semantic_mismatch",
                "Verified Skill semantic hash does not match the executable plan.",
            )
        signing_key_id = resolution["signing_key_id"]
        if signing_key_id is None:
            detail = (
                "Production and staging require a signed verified Skill package."
                if profile in PRODUCTION_ENVIRONMENTS
                else "The P6 VerifiedSkillArtifact contract requires a signing key."
            )
            raise _rejected(detail)

        package_hash = resolution["package_hash"]
        package_digest = sha256_from_hash_ref(package_hash)
        package_id = f"nsp:{package_digest}"
        try:
            admission_record = self._admission_source.current_admission(
                tenant_id=tenant,
                package_id=package_id,
                package_hash=package_hash,
                signing_key_id=signing_key_id,
                trust_policy_id=policy_id,
                observed_at=observed,
            )
        except SkillArtifactGatewayError:
            raise
        except Exception as exc:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_trust_unavailable",
                "Current Skill package trust state is unavailable.",
                True,
            ) from exc
        if admission_record is None:
            raise _rejected("No current package admission decision exists.")

        trust, admission_hash, admission_ref = _validated_admission(
            admission_record,
            package_id=package_id,
            package_hash=package_hash,
            signing_key_id=signing_key_id,
            trust_policy_id=policy_id,
            observed_at=observed,
        )
        backend_handle = _backend_handle(
            package_digest, requested_skill, requested_version
        )
        identity_hash = semantic_sha256_hash_ref(
            {
                "tenant_id": tenant,
                "skill_id": requested_skill,
                "skill_version": requested_version,
                "package_hash": package_hash,
                "trust_evidence_hash": trust["evidence_hash"],
                "admission_decision_hash": admission_hash,
                "runtime_contract_ref": contract_ref,
            }
        )
        artifact: dict[str, Any] = {
            "schema_version": VERIFIED_SKILL_ARTIFACT_SCHEMA_VERSION,
            "artifact_ref": (
                "AE:NSL_ARTIFACT:" + sha256_from_hash_ref(identity_hash)
            ),
            "backend_artifact_handle": backend_handle,
            "skill_id": requested_skill,
            "skill_version": requested_version,
            "skill_semantic_hash": expected_hash,
            "package_id": package_id,
            "package_hash": package_hash,
            "publisher_id": trust["publisher_id"],
            "signing_key_id": signing_key_id,
            "runtime_contract_ref": contract_ref,
            "trust_evidence": _bounded_trust_projection(trust),
            "artifact_admission_decision_ref": admission_ref,
            "artifact_admission_decision_hash": admission_hash,
        }
        artifact["artifact_hash"] = semantic_sha256_hash_ref(artifact)
        normalized = validate_verified_skill_artifact(artifact)
        try:
            return self._repository.save(tenant_id=tenant, artifact=normalized)
        except SkillArtifactGatewayError:
            raise
        except Exception as exc:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_persistence_unavailable",
                "Verified Skill artifact persistence is unavailable.",
                True,
            ) from exc


class SqlAlchemySkillArtifactRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(
        self, *, tenant_id: str, artifact: Mapping[str, Any]
    ) -> dict[str, Any]:
        tenant = _bounded_text("tenant_id", tenant_id, 128)
        normalized = validate_verified_skill_artifact(artifact)
        params = {
            "tenant_id": tenant,
            "artifact_ref": normalized["artifact_ref"],
            "artifact_hash": normalized["artifact_hash"],
            "skill_id": normalized["skill_id"],
            "skill_version": normalized["skill_version"],
            "package_hash": normalized["package_hash"],
            "verified_at": normalized["trust_evidence"]["verified_at"],
            "artifact_json": canonical_json(normalized),
        }
        try:
            with self._session_factory() as session:
                session.execute(text(_insert_sql(_dialect_name(session))), params)
                saved = _load_by_ref(session, tenant, normalized["artifact_ref"])
                if saved != normalized:
                    raise SkillArtifactGatewayError(
                        "ae.skill_artifact_immutable_conflict",
                        "Verified Skill artifact identity has different immutable content.",
                    )
                session.commit()
                return saved
        except SkillArtifactGatewayError:
            raise
        except SQLAlchemyError as exc:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_persistence_unavailable",
                "Verified Skill artifact persistence is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, artifact_ref: str
    ) -> dict[str, Any] | None:
        tenant = _bounded_text("tenant_id", tenant_id, 128)
        reference = _ref("artifact_ref", artifact_ref)
        try:
            with self._session_factory() as session:
                return _load_by_ref(session, tenant, reference)
        except SQLAlchemyError as exc:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_persistence_unavailable",
                "Verified Skill artifact persistence is unavailable.",
                True,
            ) from exc

    def get_by_hash(
        self, *, tenant_id: str, artifact_hash: str
    ) -> dict[str, Any] | None:
        tenant = _bounded_text("tenant_id", tenant_id, 128)
        digest = _hash_ref("artifact_hash", artifact_hash)
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        """
                        SELECT artifact_json FROM ae_nsl_artifact
                        WHERE tenant_id = :tenant_id AND artifact_hash = :artifact_hash
                        """
                    ),
                    {"tenant_id": tenant, "artifact_hash": digest},
                ).mappings().first()
                return None if row is None else _artifact_json(row["artifact_json"])
        except SQLAlchemyError as exc:
            raise SkillArtifactGatewayError(
                "ae.skill_artifact_persistence_unavailable",
                "Verified Skill artifact persistence is unavailable.",
                True,
            ) from exc


def validate_verified_skill_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        artifact = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("VerifiedSkillArtifact must be canonical JSON.") from exc
    fields = {
        "schema_version",
        "artifact_ref",
        "backend_artifact_handle",
        "skill_id",
        "skill_version",
        "skill_semantic_hash",
        "package_id",
        "package_hash",
        "publisher_id",
        "signing_key_id",
        "runtime_contract_ref",
        "trust_evidence",
        "artifact_admission_decision_ref",
        "artifact_admission_decision_hash",
        "artifact_hash",
    }
    if set(artifact) != fields or artifact.get("schema_version") != "1.0":
        raise _invalid("VerifiedSkillArtifact fields or schema version are invalid.")
    _ref("artifact_ref", artifact["artifact_ref"])
    _ref("backend_artifact_handle", artifact["backend_artifact_handle"])
    _selector("skill_id", artifact["skill_id"])
    _selector("skill_version", artifact["skill_version"])
    _hash_ref("skill_semantic_hash", artifact["skill_semantic_hash"])
    package_id = _ref("package_id", artifact["package_id"])
    package_hash = _hash_ref("package_hash", artifact["package_hash"])
    if package_id != f"nsp:{sha256_from_hash_ref(package_hash)}":
        raise _invalid("VerifiedSkillArtifact package identity is inconsistent.")
    _bounded_text("publisher_id", artifact["publisher_id"], 256)
    _bounded_text("signing_key_id", artifact["signing_key_id"], 256)
    _ref("runtime_contract_ref", artifact["runtime_contract_ref"])
    _validate_trust_projection(artifact["trust_evidence"])
    _ref(
        "artifact_admission_decision_ref",
        artifact["artifact_admission_decision_ref"],
    )
    _hash_ref(
        "artifact_admission_decision_hash",
        artifact["artifact_admission_decision_hash"],
    )
    supplied_hash = _hash_ref("artifact_hash", artifact["artifact_hash"])
    projection = dict(artifact)
    projection.pop("artifact_hash")
    if supplied_hash != semantic_sha256_hash_ref(projection):
        raise _invalid("VerifiedSkillArtifact hash does not match semantic content.")
    return artifact


def skill_artifact_table_sql(dialect_name: str) -> tuple[str, ...]:
    json_type = "TEXT" if dialect_name == "sqlite" else "JSONB"
    timestamp_type = "TEXT" if dialect_name == "sqlite" else "TIMESTAMPTZ"
    return (
        f"""
        CREATE TABLE ae_nsl_artifact (
            tenant_id TEXT NOT NULL,
            artifact_ref TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            skill_version TEXT NOT NULL,
            package_hash TEXT NOT NULL,
            verified_at {timestamp_type} NOT NULL,
            artifact_json {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, artifact_ref),
            UNIQUE (tenant_id, artifact_hash)
        )
        """,
        """
        CREATE INDEX idx_ae_nsl_artifact_skill
        ON ae_nsl_artifact (tenant_id, skill_id, skill_version, package_hash)
        """,
    )


def _resolved_projection(resolved: object) -> dict[str, Any]:
    skill = getattr(resolved, "skill", None)
    if skill is None:
        raise _rejected("Verified Skill resolution has no Skill object.")
    signer = getattr(resolved, "signer_key_id", None)
    return {
        "skill_id": _selector("resolved.skill_id", getattr(skill, "skill_id", None)),
        "skill_version": _selector(
            "resolved.skill_version", getattr(skill, "skill_version", None)
        ),
        "skill_semantic_hash": _hash_ref(
            "resolved.semantic_hash", getattr(skill, "semantic_hash", None)
        ),
        "package_hash": _hash_ref(
            "resolved.package_hash", getattr(resolved, "package_hash", None)
        ),
        "signing_key_id": (
            None if signer is None else _bounded_text("signer_key_id", signer, 256)
        ),
    }


def _validated_admission(
    record: Mapping[str, Any],
    *,
    package_id: str,
    package_hash: str,
    signing_key_id: str,
    trust_policy_id: str,
    observed_at: str,
) -> tuple[dict[str, Any], str, str]:
    if not isinstance(record, Mapping):
        raise _rejected("Current package admission record is invalid.")
    trust_raw = record.get("trust_evidence")
    admission_raw = record.get("admission_decision")
    if not isinstance(trust_raw, Mapping) or not isinstance(admission_raw, Mapping):
        raise _rejected("Current package trust or admission evidence is missing.")
    trust = _validate_full_trust(
        trust_raw,
        package_id=package_id,
        package_hash=package_hash,
        signing_key_id=signing_key_id,
        trust_policy_id=trust_policy_id,
        observed_at=observed_at,
    )
    admission = _validate_admission_decision(
        admission_raw,
        trust=trust,
        package_id=package_id,
        package_hash=package_hash,
        signing_key_id=signing_key_id,
        trust_policy_id=trust_policy_id,
        observed_at=observed_at,
    )
    decision_hash = semantic_sha256_hash_ref(
        {key: item for key, item in admission.items() if key != "decision_id"}
    )
    supplied_hash = record.get("admission_decision_hash")
    if supplied_hash is not None and _hash_ref(
        "admission_decision_hash", supplied_hash
    ) != decision_hash:
        raise _rejected("Artifact admission decision hash is inconsistent.")
    return trust, decision_hash, _ref("decision_id", admission["decision_id"])


def _validate_full_trust(
    value: Mapping[str, Any],
    *,
    package_id: str,
    package_hash: str,
    signing_key_id: str,
    trust_policy_id: str,
    observed_at: str,
) -> dict[str, Any]:
    required = {
        "evidence_ref",
        "package_id",
        "package_hash",
        "publisher_id",
        "signing_key_id",
        "verified_at",
        "trust_policy_id",
        "trust_status",
        "governance_status",
        "governance_decision_ref",
    }
    allowed = required | {"evidence_hash"}
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise _rejected("Package trust evidence fields are invalid.")
    trust = {
        "evidence_ref": _ref("evidence_ref", value["evidence_ref"]),
        "package_id": _ref("package_id", value["package_id"]),
        "package_hash": _hash_ref("package_hash", value["package_hash"]),
        "publisher_id": _bounded_text("publisher_id", value["publisher_id"], 256),
        "signing_key_id": _bounded_text(
            "signing_key_id", value["signing_key_id"], 256
        ),
        "verified_at": _timestamp("verified_at", value["verified_at"]),
        "trust_policy_id": _bounded_text(
            "trust_policy_id", value["trust_policy_id"], 256
        ),
        "trust_status": value["trust_status"],
        "governance_status": value["governance_status"],
        "governance_decision_ref": _ref(
            "governance_decision_ref", value["governance_decision_ref"]
        ),
    }
    if (
        trust["package_id"] != package_id
        or trust["package_hash"] != package_hash
        or trust["signing_key_id"] != signing_key_id
        or trust["trust_policy_id"] != trust_policy_id
        or trust["trust_status"] != "VALID"
        or trust["governance_status"] != "ACTIVE"
    ):
        raise _rejected("Package trust evidence is not current and admissible.")
    if _parse_timestamp(trust["verified_at"]) > _parse_timestamp(observed_at):
        raise _rejected("Package trust verification time is in the future.")
    calculated_hash = semantic_sha256_hash_ref(_trust_semantic_projection(trust))
    supplied_hash = value.get("evidence_hash")
    if supplied_hash is not None and _hash_ref(
        "evidence_hash", supplied_hash
    ) != calculated_hash:
        raise _rejected("Package trust evidence hash is inconsistent.")
    trust["evidence_hash"] = calculated_hash
    return trust


def _validate_admission_decision(
    value: Mapping[str, Any],
    *,
    trust: Mapping[str, Any],
    package_id: str,
    package_hash: str,
    signing_key_id: str,
    trust_policy_id: str,
    observed_at: str,
) -> dict[str, Any]:
    fields = {
        "decision_id",
        "decision",
        "package_id",
        "package_hash",
        "publisher_id",
        "signing_key_id",
        "governance_status",
        "trust_policy_id",
        "package_trust_evidence_ref",
        "reason_codes",
        "decided_at",
    }
    if set(value) != fields:
        raise _rejected("Artifact admission decision fields are invalid.")
    reasons = value["reason_codes"]
    if not isinstance(reasons, list) or any(
        not isinstance(item, str) or not item or len(item) > 256 for item in reasons
    ):
        raise _rejected("Artifact admission reason codes are invalid.")
    decision = {
        "decision_id": _ref("decision_id", value["decision_id"]),
        "decision": value["decision"],
        "package_id": _ref("package_id", value["package_id"]),
        "package_hash": _hash_ref("package_hash", value["package_hash"]),
        "publisher_id": _bounded_text("publisher_id", value["publisher_id"], 256),
        "signing_key_id": _bounded_text(
            "signing_key_id", value["signing_key_id"], 256
        ),
        "governance_status": value["governance_status"],
        "trust_policy_id": _bounded_text(
            "trust_policy_id", value["trust_policy_id"], 256
        ),
        "package_trust_evidence_ref": _ref(
            "package_trust_evidence_ref", value["package_trust_evidence_ref"]
        ),
        "reason_codes": list(reasons),
        "decided_at": _timestamp("decided_at", value["decided_at"]),
    }
    if (
        decision["decision"] != "ADMITTED"
        or decision["governance_status"] != "ACTIVE"
        or decision["reason_codes"]
        or decision["package_id"] != package_id
        or decision["package_hash"] != package_hash
        or decision["publisher_id"] != trust["publisher_id"]
        or decision["signing_key_id"] != signing_key_id
        or decision["trust_policy_id"] != trust_policy_id
        or decision["package_trust_evidence_ref"] != trust["evidence_ref"]
    ):
        raise _rejected("Artifact admission decision does not admit this package.")
    if _parse_timestamp(decision["decided_at"]) > _parse_timestamp(observed_at):
        raise _rejected("Artifact admission decision time is in the future.")
    return decision


def _validate_trust_projection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("VerifiedSkillArtifact trust_evidence is invalid.")
    fields = {
        "evidence_ref",
        "evidence_hash",
        "verified_at",
        "trust_policy_id",
        "trust_status",
        "governance_status",
        "governance_decision_ref",
    }
    if set(value) != fields:
        raise _invalid("VerifiedSkillArtifact trust evidence fields are invalid.")
    trust = {
        "evidence_ref": _ref("evidence_ref", value["evidence_ref"]),
        "evidence_hash": _hash_ref("evidence_hash", value["evidence_hash"]),
        "verified_at": _timestamp("verified_at", value["verified_at"]),
        "trust_policy_id": _bounded_text(
            "trust_policy_id", value["trust_policy_id"], 256
        ),
        "trust_status": value["trust_status"],
        "governance_status": value["governance_status"],
        "governance_decision_ref": _ref(
            "governance_decision_ref", value["governance_decision_ref"]
        ),
    }
    if trust["trust_status"] != "VALID" or trust["governance_status"] != "ACTIVE":
        raise _invalid("VerifiedSkillArtifact trust status is invalid.")
    expected = semantic_sha256_hash_ref(_trust_semantic_projection(trust))
    if trust["evidence_hash"] != expected:
        raise _invalid("VerifiedSkillArtifact trust evidence hash is invalid.")
    return trust


def _bounded_trust_projection(trust: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence_ref": trust["evidence_ref"],
        "evidence_hash": trust["evidence_hash"],
        "verified_at": trust["verified_at"],
        "trust_policy_id": trust["trust_policy_id"],
        "trust_status": trust["trust_status"],
        "governance_status": trust["governance_status"],
        "governance_decision_ref": trust["governance_decision_ref"],
    }


def _trust_semantic_projection(trust: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence_ref": trust["evidence_ref"],
        "verified_at": trust["verified_at"],
        "trust_policy_id": trust["trust_policy_id"],
        "trust_status": trust["trust_status"],
        "governance_status": trust["governance_status"],
        "governance_decision_ref": trust["governance_decision_ref"],
    }


def _backend_handle(package_digest: str, skill_id: str, version: str) -> str:
    handle = (
        f"nsp+sha256://{package_digest}/"
        f"{quote(skill_id, safe='._-')}@{quote(version, safe='._-')}"
    )
    return _ref("backend_artifact_handle", handle)


def _load_by_ref(
    session: Session, tenant_id: str, artifact_ref: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT artifact_json FROM ae_nsl_artifact
            WHERE tenant_id = :tenant_id AND artifact_ref = :artifact_ref
            """
        ),
        {"tenant_id": tenant_id, "artifact_ref": artifact_ref},
    ).mappings().first()
    return None if row is None else _artifact_json(row["artifact_json"])


def _artifact_json(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise _invalid("Persisted VerifiedSkillArtifact JSON is invalid.")
    return validate_verified_skill_artifact(value)


def _insert_sql(dialect_name: str) -> str:
    artifact_json = (
        ":artifact_json" if dialect_name == "sqlite" else "CAST(:artifact_json AS JSONB)"
    )
    verified_at = (
        ":verified_at"
        if dialect_name == "sqlite"
        else "CAST(:verified_at AS TIMESTAMPTZ)"
    )
    return f"""
        INSERT INTO ae_nsl_artifact (
            tenant_id, artifact_ref, artifact_hash, skill_id, skill_version,
            package_hash, verified_at, artifact_json
        ) VALUES (
            :tenant_id, :artifact_ref, :artifact_hash, :skill_id, :skill_version,
            :package_hash, {verified_at}, {artifact_json}
        ) ON CONFLICT (tenant_id, artifact_ref) DO NOTHING
    """


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return "" if bind is None else str(bind.dialect.name)


def _environment(value: object) -> str:
    normalized = _bounded_text("environment", value, 32).lower()
    if normalized not in {"development", "test", "staging", "production"}:
        raise _invalid("Skill artifact environment is invalid.")
    return normalized


def _selector(field: str, value: object) -> str:
    if not isinstance(value, str) or _SELECTOR.fullmatch(value) is None:
        raise _invalid(f"{field} must be a bounded printable ASCII selector.")
    return value


def _bounded_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value


def _ref(field: str, value: object) -> str:
    return _bounded_text(field, value, 512)


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a lowercase SHA-256 hash reference.") from exc


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC 3339 timestamp.")
    parsed = _parse_timestamp(value)
    return parsed.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("Timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise _invalid("Timestamp must include a timezone.")
    return parsed.astimezone(UTC)


def _invalid(detail: str) -> SkillArtifactGatewayError:
    return SkillArtifactGatewayError("ae.skill_artifact_invalid", detail)


def _rejected(detail: str) -> SkillArtifactGatewayError:
    return SkillArtifactGatewayError("ae.skill_artifact_trust_rejected", detail)
