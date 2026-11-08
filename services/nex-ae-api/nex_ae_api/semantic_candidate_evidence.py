from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from nex_runtime.object_storage import ObjectStorageError, S3ObjectStore, build_owner_object_key
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
    validate_sha256_digest,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.private_object_store import (
    AePrivateObjectStorageError,
    ae_private_storage_mode,
    build_ae_private_object_store,
)


SEMANTIC_CANDIDATE_SCHEMA_VERSION = "p65.semantic_candidate_evidence.v1"
SEMANTIC_CANDIDATE_STORAGE_ENV = "NEX_AE_SEMANTIC_CANDIDATE_STORAGE_ROOT"
SEMANTIC_CANDIDATE_STORAGE_SCHEME = "ae://semantic-candidates/"
MAX_SEMANTIC_CANDIDATE_BYTES = 1024 * 1024
SEMANTIC_STAGES = frozenset({"INTENT", "CONTEXT", "PLAN"})
VALIDATION_OUTCOMES = frozenset({"ADMITTED", "REJECTED", "FAILED"})
DIRECTIVES = frozenset(
    {
        "CONTINUE",
        "SHADOW_ONLY",
        "CLARIFICATION_REQUIRED",
        "CONTEXT_REFRESH_REQUIRED",
        "REPLAN_REQUIRED",
        "BLOCKED",
    }
)
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_STORAGE_REF = re.compile(
    r"^ae://semantic-candidates/([0-9a-f-]{36})/([0-9a-f]{64})\.json$"
)


@dataclass(frozen=True)
class SemanticCandidateEvidenceError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SemanticCandidateStorage(Protocol):
    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> str: ...

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None: ...

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> bool: ...


def build_semantic_candidate_payload(
    *, candidate_id: str, candidate: Mapping[str, Any]
) -> dict[str, Any]:
    candidate_id = _uuid_text("candidate_id", candidate_id)
    try:
        content = canonical_json(dict(candidate))
    except (TypeError, ValueError) as exc:
        raise _invalid("Semantic candidate must be canonical JSON.") from exc
    encoded = content.encode("utf-8")
    if not encoded or len(encoded) > MAX_SEMANTIC_CANDIDATE_BYTES:
        raise _invalid("Semantic candidate payload size is outside the boundary.")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "candidate_id": candidate_id,
        "content": content,
        "content_sha256": digest,
        "size_bytes": len(encoded),
        "storage_ref": (
            f"{SEMANTIC_CANDIDATE_STORAGE_SCHEME}{candidate_id}/{digest}.json"
        ),
    }


def semantic_candidate_payload_metadata(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _validate_payload(payload, require_content=True)
    return {key: value for key, value in normalized.items() if key != "content"}


@dataclass
class InMemorySemanticCandidateStorage:
    payloads: dict[tuple[str, str, str], bytes] = field(default_factory=dict)

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> str:
        normalized = _validate_payload(payload, require_content=True)
        key = _owner_key(tenant_id, owner_subject_id, normalized["storage_ref"])
        encoded = str(normalized["content"]).encode("utf-8")
        existing = self.payloads.get(key)
        if existing is not None and existing != encoded:
            raise _integrity_error()
        self.payloads[key] = encoded
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        normalized = _validate_payload(metadata, require_content=False)
        payload = self.payloads.get(
            _owner_key(tenant_id, owner_subject_id, normalized["storage_ref"])
        )
        return None if payload is None else _decode_candidate(payload, normalized)

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> bool:
        normalized = _validate_payload(metadata, require_content=False)
        return (
            self.payloads.pop(
                _owner_key(tenant_id, owner_subject_id, normalized["storage_ref"]),
                None,
            )
            is not None
        )


@dataclass(frozen=True)
class LocalSemanticCandidateStorage:
    root: Path

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> str:
        normalized = _validate_payload(payload, require_content=True)
        path = self._path(tenant_id, owner_subject_id, normalized["storage_ref"])
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = str(normalized["content"]).encode("utf-8")
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise _unavailable() from exc
            if existing != encoded:
                raise _integrity_error()
            return str(normalized["storage_ref"])
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
            path.chmod(0o600)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise _unavailable() from exc
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        normalized = _validate_payload(metadata, require_content=False)
        path = self._path(tenant_id, owner_subject_id, normalized["storage_ref"])
        if not path.exists():
            return None
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise _unavailable() from exc
        return _decode_candidate(payload, normalized)

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> bool:
        normalized = _validate_payload(metadata, require_content=False)
        path = self._path(tenant_id, owner_subject_id, normalized["storage_ref"])
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise _unavailable() from exc
        return True

    def _path(
        self, tenant_id: str, owner_subject_id: str, storage_ref: object
    ) -> Path:
        owner_scope = (
            f"{_required_text('tenant_id', tenant_id, 128)}\0"
            f"{_required_text('owner_subject_id', owner_subject_id, 200)}"
        )
        owner_hash = hashlib.sha256(owner_scope.encode()).hexdigest()
        relative = _storage_ref_relative_path(storage_ref)
        root = self.root.resolve()
        path = root.joinpath(owner_hash[:2], owner_hash, *relative.split("/")).resolve(
            strict=False
        )
        if not path.is_relative_to(root):
            raise _invalid("Semantic candidate storage reference escapes its root.")
        return path


@dataclass(frozen=True)
class S3SemanticCandidateStorage:
    object_store: S3ObjectStore

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> str:
        normalized = _validate_payload(payload, require_content=True)
        encoded = str(normalized["content"]).encode("utf-8")
        try:
            self.object_store.put_immutable(
                key=self._key(tenant_id, owner_subject_id, normalized["candidate_id"]),
                payload=encoded,
                expected_sha256=str(normalized["content_sha256"]),
                content_type="application/json",
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        normalized = _validate_payload(metadata, require_content=False)
        try:
            payload = self.object_store.get_bytes(
                key=self._key(tenant_id, owner_subject_id, normalized["candidate_id"]),
                expected_sha256=str(normalized["content_sha256"]),
                expected_size_bytes=int(normalized["size_bytes"]),
                max_size_bytes=MAX_SEMANTIC_CANDIDATE_BYTES,
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return None if payload is None else _decode_candidate(payload, normalized)

    def delete(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> bool:
        normalized = _validate_payload(metadata, require_content=False)
        key = self._key(tenant_id, owner_subject_id, normalized["candidate_id"])
        try:
            if self.object_store.head(key) is None:
                return False
            self.object_store.delete(key)
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return True

    @staticmethod
    def _key(tenant_id: str, owner_subject_id: str, candidate_id: object) -> str:
        try:
            return build_owner_object_key(
                payload_family="semantic-candidate",
                tenant_id=_required_text("tenant_id", tenant_id, 128),
                subject_id=_required_text(
                    "owner_subject_id", owner_subject_id, 200
                ),
                content_id=_uuid_text("candidate_id", candidate_id),
                suffix="json",
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc


def build_default_semantic_candidate_storage(
    environ: Mapping[str, str] | None = None,
) -> SemanticCandidateStorage:
    env = os.environ if environ is None else environ
    try:
        mode = ae_private_storage_mode(env)
        if mode == "S3":
            return S3SemanticCandidateStorage(build_ae_private_object_store(env))
    except AePrivateObjectStorageError as exc:
        raise SemanticCandidateEvidenceError(
            exc.error_code, exc.detail, exc.retryable
        ) from exc
    root = env.get(SEMANTIC_CANDIDATE_STORAGE_ENV)
    if mode == "FILESYSTEM" and (not isinstance(root, str) or not root.strip()):
        raise _invalid("AE semantic candidate filesystem root is required.")
    if not isinstance(root, str) or not root.strip():
        return InMemorySemanticCandidateStorage()
    return LocalSemanticCandidateStorage(Path(root.strip()))


def build_semantic_candidate_evidence(
    *,
    tenant_id: str,
    owner_subject_id: str,
    candidate_id: str,
    execution_id: str,
    semantic_stage: str,
    candidate_revision: int,
    candidate_payload: Mapping[str, Any],
    provider_output_sha256: str,
    input_context_hash: str,
    prompt_provenance: Mapping[str, Any],
    model_provenance: Mapping[str, Any],
    request_id: str,
    trace_id: str,
    admission_policy_ref: str,
    directive: str,
    failure_code: str | None,
    created_at: str,
) -> dict[str, Any]:
    payload = _validate_payload(candidate_payload, require_content=True)
    candidate_hash = semantic_sha256_hash_ref(json.loads(str(payload["content"])))
    outcome = "ADMITTED" if directive == "CONTINUE" else "REJECTED"
    evidence = {
        "schema_version": SEMANTIC_CANDIDATE_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "owner_subject_id": owner_subject_id,
        "candidate_id": candidate_id,
        "execution_id": execution_id,
        "semantic_stage": semantic_stage,
        "candidate_revision": candidate_revision,
        "candidate_hash": candidate_hash,
        "candidate_payload_storage_ref": payload["storage_ref"],
        "candidate_payload_size_bytes": payload["size_bytes"],
        "provider_output_sha256": provider_output_sha256,
        "input_context_hash": input_context_hash,
        "prompt_binding_id": prompt_provenance.get("prompt_binding_id"),
        "prompt_binding_key": prompt_provenance.get("prompt_binding_key"),
        "prompt_template_version_id": prompt_provenance.get(
            "prompt_template_version_id"
        ),
        "prompt_template_version": prompt_provenance.get(
            "prompt_template_version"
        ),
        "prompt_content_sha256": prompt_provenance.get("prompt_content_sha256"),
        "rendered_prompt_hash": prompt_provenance.get("rendered_prompt_hash"),
        "model_profile": model_provenance.get("model_profile"),
        "model_ref": model_provenance.get("model_ref"),
        "deployment_id": model_provenance.get("deployment_id"),
        "mo_generation_id": model_provenance.get("mo_generation_id"),
        "request_id": request_id,
        "trace_id": trace_id,
        "admission_policy_ref": admission_policy_ref,
        "validation_outcome": outcome,
        "directive": directive,
        "failure_code": failure_code,
        "created_at": created_at,
    }
    return validate_semantic_candidate_evidence(evidence)


def validate_semantic_candidate_evidence(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        record = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("Semantic candidate evidence must be canonical JSON.") from exc
    fields = {
        "schema_version",
        "tenant_id",
        "owner_subject_id",
        "candidate_id",
        "execution_id",
        "semantic_stage",
        "candidate_revision",
        "candidate_hash",
        "candidate_payload_storage_ref",
        "candidate_payload_size_bytes",
        "provider_output_sha256",
        "input_context_hash",
        "prompt_binding_id",
        "prompt_binding_key",
        "prompt_template_version_id",
        "prompt_template_version",
        "prompt_content_sha256",
        "rendered_prompt_hash",
        "model_profile",
        "model_ref",
        "deployment_id",
        "mo_generation_id",
        "request_id",
        "trace_id",
        "admission_policy_ref",
        "validation_outcome",
        "directive",
        "failure_code",
        "created_at",
    }
    if set(record) != fields or record.get("schema_version") != SEMANTIC_CANDIDATE_SCHEMA_VERSION:
        raise _invalid("Semantic candidate evidence fields do not match v1.")
    _required_text("tenant_id", record["tenant_id"], 128)
    _required_text("owner_subject_id", record["owner_subject_id"], 200)
    candidate_id = _uuid_text("candidate_id", record["candidate_id"])
    _uuid_text("execution_id", record["execution_id"])
    if record["semantic_stage"] not in SEMANTIC_STAGES:
        raise _invalid("Semantic candidate stage is invalid.")
    _bounded_int("candidate_revision", record["candidate_revision"], 1, 99)
    candidate_hash = record["candidate_hash"]
    storage_ref = record["candidate_payload_storage_ref"]
    size_bytes = record["candidate_payload_size_bytes"]
    if candidate_hash is not None:
        _hash_ref("candidate_hash", candidate_hash)
    if storage_ref is not None:
        match = _STORAGE_REF.fullmatch(str(storage_ref))
        if match is None or match.group(1) != candidate_id:
            raise _invalid("Semantic candidate storage reference is invalid.")
    if size_bytes is not None:
        _bounded_int(
            "candidate_payload_size_bytes",
            size_bytes,
            1,
            MAX_SEMANTIC_CANDIDATE_BYTES,
        )
    for field_name in (
        "provider_output_sha256",
        "prompt_content_sha256",
        "rendered_prompt_hash",
    ):
        _digest(field_name, record[field_name])
    _hash_ref("input_context_hash", record["input_context_hash"])
    _uuid_text("prompt_binding_id", record["prompt_binding_id"])
    _uuid_text("prompt_template_version_id", record["prompt_template_version_id"])
    for field_name, maximum in (
        ("prompt_binding_key", 200),
        ("prompt_template_version", 64),
        ("model_profile", 128),
        ("model_ref", 256),
        ("deployment_id", 256),
        ("mo_generation_id", 256),
        ("request_id", 200),
        ("admission_policy_ref", 256),
    ):
        _required_text(field_name, record[field_name], maximum)
    if not isinstance(record["trace_id"], str) or _TRACE_ID.fullmatch(record["trace_id"]) is None:
        raise _invalid("Semantic candidate trace_id is invalid.")
    if record["validation_outcome"] not in VALIDATION_OUTCOMES:
        raise _invalid("Semantic candidate validation outcome is invalid.")
    if record["directive"] not in DIRECTIVES:
        raise _invalid("Semantic candidate directive is invalid.")
    failure_code = record["failure_code"]
    if failure_code is not None and (
        not isinstance(failure_code, str) or _FAILURE_CODE.fullmatch(failure_code) is None
    ):
        raise _invalid("Semantic candidate failure code is invalid.")
    _datetime_text("created_at", record["created_at"])
    if record["validation_outcome"] == "ADMITTED" and (
        record["directive"] != "CONTINUE"
        or failure_code is not None
        or candidate_hash is None
        or storage_ref is None
        or size_bytes is None
    ):
        raise _invalid("Admitted semantic candidate evidence is incomplete.")
    if record["validation_outcome"] == "REJECTED" and record["directive"] == "CONTINUE":
        raise _invalid("Rejected semantic candidate cannot continue.")
    return record


class SqlAlchemySemanticCandidateEvidenceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_semantic_candidate_evidence(evidence)
        params = _evidence_params(normalized)
        try:
            with self._session_factory() as session:
                session.execute(text(_insert_sql(_dialect_name(session))), params)
                saved = _load_evidence(
                    session, normalized["tenant_id"], normalized["candidate_id"]
                )
                if saved is None:
                    conflict = _load_stage_evidence(
                        session,
                        normalized["tenant_id"],
                        normalized["execution_id"],
                        normalized["semantic_stage"],
                        normalized["candidate_revision"],
                    )
                    if conflict is not None:
                        raise SemanticCandidateEvidenceError(
                            "ae.semantic_candidate_revision_conflict",
                            "A different candidate owns this semantic stage revision.",
                        )
                    raise SemanticCandidateEvidenceError(
                        "ae.semantic_candidate_write_conflict",
                        "Semantic candidate evidence could not be reloaded.",
                        True,
                    )
                if saved != normalized:
                    raise SemanticCandidateEvidenceError(
                        "ae.semantic_candidate_immutable_conflict",
                        "Semantic candidate evidence identity has different content.",
                    )
                session.commit()
                return saved
        except SemanticCandidateEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise SemanticCandidateEvidenceError(
                "ae.semantic_candidate_store_unavailable",
                "AE semantic candidate evidence store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, candidate_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        candidate_id = _uuid_text("candidate_id", candidate_id)
        try:
            with self._session_factory() as session:
                return _load_evidence(session, tenant_id, candidate_id)
        except SQLAlchemyError as exc:
            raise SemanticCandidateEvidenceError(
                "ae.semantic_candidate_store_unavailable",
                "AE semantic candidate evidence store is unavailable.",
                True,
            ) from exc


def candidate_payload_metadata_from_evidence(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_semantic_candidate_evidence(evidence)
    if (
        normalized["candidate_hash"] is None
        or normalized["candidate_payload_storage_ref"] is None
        or normalized["candidate_payload_size_bytes"] is None
    ):
        raise _invalid("Semantic candidate evidence has no persisted payload.")
    return {
        "candidate_id": normalized["candidate_id"],
        "content_sha256": str(normalized["candidate_hash"]).removeprefix("sha256:"),
        "size_bytes": normalized["candidate_payload_size_bytes"],
        "storage_ref": normalized["candidate_payload_storage_ref"],
    }


def _evidence_params(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(value),
        "agent_execution_id": value["execution_id"],
        "evidence_json": canonical_json(value),
    }


def _insert_sql(dialect_name: str) -> str:
    evidence_json = (
        "CAST(:evidence_json AS jsonb)"
        if dialect_name == "postgresql"
        else ":evidence_json"
    )
    return f"""
        INSERT INTO ae_semantic_candidate (
            tenant_id, candidate_id, owner_subject_id, agent_execution_id,
            semantic_stage, candidate_revision, candidate_hash,
            candidate_payload_storage_ref, candidate_payload_size_bytes,
            provider_output_sha256, input_context_hash, prompt_binding_id,
            prompt_binding_key, prompt_template_version_id,
            prompt_template_version, prompt_content_sha256,
            rendered_prompt_hash, model_profile, model_ref, deployment_id,
            mo_generation_id, request_id, trace_id, admission_policy_ref,
            validation_outcome, directive, failure_code, evidence_json, created_at
        ) VALUES (
            :tenant_id, :candidate_id, :owner_subject_id, :agent_execution_id,
            :semantic_stage, :candidate_revision, :candidate_hash,
            :candidate_payload_storage_ref, :candidate_payload_size_bytes,
            :provider_output_sha256, :input_context_hash, :prompt_binding_id,
            :prompt_binding_key, :prompt_template_version_id,
            :prompt_template_version, :prompt_content_sha256,
            :rendered_prompt_hash, :model_profile, :model_ref, :deployment_id,
            :mo_generation_id, :request_id, :trace_id, :admission_policy_ref,
            :validation_outcome, :directive, :failure_code, {evidence_json}, :created_at
        ) ON CONFLICT DO NOTHING
    """


def _load_evidence(
    session: Session, tenant_id: str, candidate_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT evidence_json FROM ae_semantic_candidate "
            "WHERE tenant_id = :tenant_id AND candidate_id = :candidate_id"
        ),
        {"tenant_id": tenant_id, "candidate_id": candidate_id},
    ).mappings().first()
    return None if row is None else validate_semantic_candidate_evidence(
        _json_object(row["evidence_json"])
    )


def _load_stage_evidence(
    session: Session,
    tenant_id: str,
    execution_id: str,
    semantic_stage: str,
    candidate_revision: int,
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT evidence_json FROM ae_semantic_candidate "
            "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id "
            "AND semantic_stage = :semantic_stage "
            "AND candidate_revision = :candidate_revision"
        ),
        {
            "tenant_id": tenant_id,
            "execution_id": execution_id,
            "semantic_stage": semantic_stage,
            "candidate_revision": candidate_revision,
        },
    ).mappings().first()
    return None if row is None else validate_semantic_candidate_evidence(
        _json_object(row["evidence_json"])
    )


def _validate_payload(
    value: Mapping[str, Any], *, require_content: bool
) -> dict[str, Any]:
    fields = {"candidate_id", "content_sha256", "size_bytes", "storage_ref"}
    if require_content:
        fields.add("content")
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Semantic candidate payload shape is invalid.")
    candidate_id = _uuid_text("candidate_id", value.get("candidate_id"))
    digest = _digest("content_sha256", value.get("content_sha256"))
    size = _bounded_int(
        "size_bytes", value.get("size_bytes"), 1, MAX_SEMANTIC_CANDIDATE_BYTES
    )
    expected_ref = f"{SEMANTIC_CANDIDATE_STORAGE_SCHEME}{candidate_id}/{digest}.json"
    if value.get("storage_ref") != expected_ref:
        raise _invalid("Semantic candidate storage reference is inconsistent.")
    normalized = {
        "candidate_id": candidate_id,
        "content_sha256": digest,
        "size_bytes": size,
        "storage_ref": expected_ref,
    }
    if require_content:
        content = value.get("content")
        if not isinstance(content, str):
            raise _invalid("Semantic candidate content must be JSON text.")
        _verify_payload(content.encode("utf-8"), digest=digest, size=size)
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise _invalid("Semantic candidate content is not JSON.") from exc
        if not isinstance(parsed, dict) or canonical_json(parsed) != content:
            raise _invalid("Semantic candidate content is not canonical JSON.")
        normalized["content"] = content
    return normalized


def _decode_candidate(payload: bytes, metadata: Mapping[str, Any]) -> dict[str, Any]:
    _verify_payload(
        payload,
        digest=str(metadata["content_sha256"]),
        size=int(metadata["size_bytes"]),
    )
    try:
        content = payload.decode("utf-8")
        value = json.loads(content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise _integrity_error() from exc
    if not isinstance(value, dict) or canonical_json(value) != content:
        raise _integrity_error()
    return value


def _verify_payload(payload: bytes, *, digest: str, size: int) -> None:
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise _integrity_error()


def _storage_ref_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("Semantic candidate storage reference is invalid.")
    match = _STORAGE_REF.fullmatch(value)
    if match is None:
        raise _invalid("Semantic candidate storage reference is invalid.")
    return value.removeprefix(SEMANTIC_CANDIDATE_STORAGE_SCHEME)


def _owner_key(
    tenant_id: str, owner_subject_id: str, storage_ref: object
) -> tuple[str, str, str]:
    return (
        _required_text("tenant_id", tenant_id, 128),
        _required_text("owner_subject_id", owner_subject_id, 200),
        _storage_ref_relative_path(storage_ref),
    )


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise _invalid("Stored semantic candidate evidence is invalid JSON.") from exc
        if isinstance(parsed, dict):
            return parsed
    raise _invalid("Stored semantic candidate evidence is invalid JSON.")


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return "" if bind is None else bind.dialect.name


def _uuid_text(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} must be a UUID.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a UUID.") from exc


def _required_text(field_name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field_name} must be bounded text.")
    return value.strip()


def _bounded_int(field_name: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _invalid(f"{field_name} is outside its numeric boundary.")
    return value


def _digest(field_name: str, value: object) -> str:
    try:
        return validate_sha256_digest(value)
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a SHA-256 digest.") from exc


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference.") from exc


def _datetime_text(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} must be a timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field_name} must include timezone information.")
    return value


def _object_storage_error(exc: ObjectStorageError) -> SemanticCandidateEvidenceError:
    if exc.retryable:
        return _unavailable()
    return _integrity_error()


def _invalid(detail: str) -> SemanticCandidateEvidenceError:
    return SemanticCandidateEvidenceError(
        "ae.semantic_candidate_evidence_invalid", detail
    )


def _integrity_error() -> SemanticCandidateEvidenceError:
    return SemanticCandidateEvidenceError(
        "ae.semantic_candidate_payload_integrity_failed",
        "Semantic candidate payload integrity validation failed.",
    )


def _unavailable() -> SemanticCandidateEvidenceError:
    return SemanticCandidateEvidenceError(
        "ae.semantic_candidate_storage_unavailable",
        "AE semantic candidate private storage is unavailable.",
        True,
    )
