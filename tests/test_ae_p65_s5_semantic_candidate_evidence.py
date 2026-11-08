from __future__ import annotations

import json
from pathlib import Path

import pytest
import nex_ae_api.semantic_candidate_evidence as evidence_module
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.semantic_candidate_evidence import (
    InMemorySemanticCandidateStorage,
    LocalSemanticCandidateStorage,
    S3SemanticCandidateStorage,
    SemanticCandidateEvidenceError,
    SqlAlchemySemanticCandidateEvidenceRepository,
    build_default_semantic_candidate_storage,
    build_semantic_candidate_evidence,
    build_semantic_candidate_payload,
    candidate_payload_metadata_from_evidence,
    semantic_candidate_payload_metadata,
    validate_semantic_candidate_evidence,
)
from nex_runtime.object_storage import ObjectStorageError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ID = "10000000-0000-4000-8000-000000000655"
EXECUTION_ID = "20000000-0000-4000-8000-000000000655"
BINDING_ID = "30000000-0000-4000-8000-000000000655"
VERSION_ID = "40000000-0000-4000-8000-000000000655"
HASH_A = "sha256:" + "a" * 64
NOW = "2026-10-17T01:00:00Z"


def _candidate() -> dict:
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": "analyze_budget",
        "confidence": 0.91,
    }


def _payload(candidate=None):
    return build_semantic_candidate_payload(
        candidate_id=CANDIDATE_ID,
        candidate=candidate or _candidate(),
    )


def _evidence(**overrides):
    candidate_id = overrides.get("candidate_id", CANDIDATE_ID)
    payload = overrides.pop(
        "candidate_payload",
        build_semantic_candidate_payload(
            candidate_id=candidate_id,
            candidate=_candidate(),
        ),
    )
    values = {
        "tenant_id": "tenant-a",
        "owner_subject_id": "user-a",
        "candidate_id": CANDIDATE_ID,
        "execution_id": EXECUTION_ID,
        "semantic_stage": "INTENT",
        "candidate_revision": 1,
        "candidate_payload": payload,
        "provider_output_sha256": "b" * 64,
        "input_context_hash": HASH_A,
        "prompt_provenance": {
            "prompt_binding_id": BINDING_ID,
            "prompt_binding_key": "ae.intent_resolution.default",
            "prompt_template_version_id": VERSION_ID,
            "prompt_template_version": "v1",
            "prompt_content_sha256": "c" * 64,
            "rendered_prompt_hash": "d" * 64,
        },
        "model_provenance": {
            "model_profile": "general-llm-default",
            "model_ref": "model-revision-a",
            "deployment_id": "deployment-a",
            "mo_generation_id": "generation-a",
        },
        "request_id": "request-a",
        "trace_id": "e" * 32,
        "admission_policy_ref": "semantic-admission://intent/model/p65.1",
        "directive": "CONTINUE",
        "failure_code": None,
        "created_at": NOW,
    }
    values.update(overrides)
    return build_semantic_candidate_evidence(**values)


def _factory():
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_semantic_candidate (
                    tenant_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                    owner_subject_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                    semantic_stage TEXT NOT NULL, candidate_revision INTEGER NOT NULL,
                    candidate_hash TEXT, candidate_payload_storage_ref TEXT,
                    candidate_payload_size_bytes INTEGER, provider_output_sha256 TEXT NOT NULL,
                    input_context_hash TEXT NOT NULL, prompt_binding_id TEXT NOT NULL,
                    prompt_binding_key TEXT NOT NULL, prompt_template_version_id TEXT NOT NULL,
                    prompt_template_version TEXT NOT NULL, prompt_content_sha256 TEXT NOT NULL,
                    rendered_prompt_hash TEXT NOT NULL, model_profile TEXT NOT NULL,
                    model_ref TEXT NOT NULL, deployment_id TEXT NOT NULL,
                    mo_generation_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL, admission_policy_ref TEXT NOT NULL,
                    validation_outcome TEXT NOT NULL, directive TEXT NOT NULL,
                    failure_code TEXT, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, candidate_id),
                    UNIQUE (tenant_id, agent_execution_id, semantic_stage, candidate_revision)
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_payload_is_canonical_content_addressed_and_owner_scoped(tmp_path: Path) -> None:
    payload = _payload()
    metadata = semantic_candidate_payload_metadata(payload)
    assert payload["storage_ref"].endswith(
        f"/{payload['content_sha256']}.json"
    )
    assert payload["content"] == json.dumps(
        _candidate(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    memory = InMemorySemanticCandidateStorage()
    assert memory.save(payload, tenant_id="tenant-a", owner_subject_id="user-a") == payload["storage_ref"]
    assert memory.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a") == _candidate()
    assert memory.load(metadata, tenant_id="tenant-a", owner_subject_id="user-b") is None

    local = LocalSemanticCandidateStorage(tmp_path)
    local.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    local.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    assert local.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a") == _candidate()
    assert local.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is True
    assert local.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is None
    assert local.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is False


def test_evidence_matches_frozen_schema_and_excludes_private_payload() -> None:
    evidence = _evidence()
    schema = json.loads(
        (ROOT / "docs/transition/P6_5/contracts/p65-semantic-candidate-evidence-v1.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(evidence)
    assert "content" not in evidence
    assert candidate_payload_metadata_from_evidence(evidence) == {
        "candidate_id": CANDIDATE_ID,
        "content_sha256": evidence["candidate_hash"].removeprefix("sha256:"),
        "size_bytes": evidence["candidate_payload_size_bytes"],
        "storage_ref": evidence["candidate_payload_storage_ref"],
    }


def test_repository_is_insert_or_verify_and_restart_safe() -> None:
    factory = _factory()
    repository = SqlAlchemySemanticCandidateEvidenceRepository(factory)
    evidence = _evidence()
    assert repository.save(evidence) == evidence
    assert repository.save(evidence) == evidence
    restarted = SqlAlchemySemanticCandidateEvidenceRepository(factory)
    assert restarted.get(tenant_id="tenant-a", candidate_id=CANDIDATE_ID) == evidence
    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM ae_semantic_candidate")).scalar_one() == 1

    changed = {**evidence, "model_ref": "other-revision"}
    with pytest.raises(SemanticCandidateEvidenceError) as raised:
        repository.save(changed)
    assert raised.value.error_code == "ae.semantic_candidate_immutable_conflict"


def test_stage_revision_conflict_and_store_unavailable_fail_closed() -> None:
    repository = SqlAlchemySemanticCandidateEvidenceRepository(_factory())
    repository.save(_evidence())
    other = _evidence(candidate_id="50000000-0000-4000-8000-000000000655")
    with pytest.raises(SemanticCandidateEvidenceError) as conflict:
        repository.save(other)
    assert conflict.value.error_code == "ae.semantic_candidate_revision_conflict"

    empty = sessionmaker(bind=create_engine("sqlite+pysqlite://", future=True))
    with pytest.raises(SemanticCandidateEvidenceError) as unavailable:
        SqlAlchemySemanticCandidateEvidenceRepository(empty).get(
            tenant_id="tenant-a", candidate_id=CANDIDATE_ID
        )
    assert unavailable.value.retryable is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "schema_version": "bad"},
        lambda value: {**value, "trace_id": "bad"},
        lambda value: {**value, "directive": "UNKNOWN"},
        lambda value: {**value, "validation_outcome": "ADMITTED", "failure_code": "FAILED"},
        lambda value: {**value, "validation_outcome": "REJECTED", "directive": "CONTINUE"},
        lambda value: {**value, "candidate_payload_storage_ref": "ae://semantic-candidates/bad"},
        lambda value: {**value, "extra": True},
    ],
)
def test_evidence_validation_rejects_contract_drift(mutation) -> None:
    with pytest.raises(SemanticCandidateEvidenceError):
        validate_semantic_candidate_evidence(mutation(_evidence()))


def test_default_storage_selection_is_fail_closed(tmp_path: Path) -> None:
    assert isinstance(build_default_semantic_candidate_storage({}), InMemorySemanticCandidateStorage)
    assert isinstance(
        build_default_semantic_candidate_storage(
            {
                "NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM",
                "NEX_AE_SEMANTIC_CANDIDATE_STORAGE_ROOT": str(tmp_path),
            }
        ),
        LocalSemanticCandidateStorage,
    )
    with pytest.raises(SemanticCandidateEvidenceError):
        build_default_semantic_candidate_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM"}
        )


def test_payload_integrity_tampering_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    local = LocalSemanticCandidateStorage(tmp_path)
    local.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    path = next(tmp_path.rglob("*.json"))
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(SemanticCandidateEvidenceError) as raised:
        local.load(
            semantic_candidate_payload_metadata(payload),
            tenant_id="tenant-a",
            owner_subject_id="user-a",
        )
    assert raised.value.error_code == "ae.semantic_candidate_payload_integrity_failed"


def test_memory_and_local_storage_reject_immutable_conflicts(tmp_path: Path) -> None:
    payload = _payload()
    metadata = semantic_candidate_payload_metadata(payload)
    memory = InMemorySemanticCandidateStorage()
    memory.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    key = next(iter(memory.payloads))
    memory.payloads[key] = b"different"
    with pytest.raises(SemanticCandidateEvidenceError) as memory_error:
        memory.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    assert memory_error.value.error_code == "ae.semantic_candidate_payload_integrity_failed"
    assert memory.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is True
    assert memory.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is False

    local = LocalSemanticCandidateStorage(tmp_path)
    local.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    next(tmp_path.rglob("*.json")).write_bytes(b"different")
    with pytest.raises(SemanticCandidateEvidenceError) as local_error:
        local.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    assert local_error.value.error_code == "ae.semantic_candidate_payload_integrity_failed"


def test_local_storage_maps_filesystem_failures_to_retryable_errors(
    tmp_path: Path, monkeypatch
) -> None:
    payload = _payload()
    metadata = semantic_candidate_payload_metadata(payload)

    replace_root = tmp_path / "replace"
    replace_storage = LocalSemanticCandidateStorage(replace_root)
    monkeypatch.setattr(evidence_module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SemanticCandidateEvidenceError) as replace_error:
        replace_storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    assert replace_error.value.retryable is True
    monkeypatch.undo()

    create_root = tmp_path / "create"
    create_storage = LocalSemanticCandidateStorage(create_root)
    monkeypatch.setattr(
        evidence_module.tempfile,
        "NamedTemporaryFile",
        lambda **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(SemanticCandidateEvidenceError) as create_error:
        create_storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    assert create_error.value.retryable is True
    monkeypatch.undo()

    read_root = tmp_path / "read"
    read_storage = LocalSemanticCandidateStorage(read_root)
    read_storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SemanticCandidateEvidenceError) as save_read_error:
        read_storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    assert save_read_error.value.retryable is True
    with pytest.raises(SemanticCandidateEvidenceError) as load_read_error:
        read_storage.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a")
    assert load_read_error.value.retryable is True
    monkeypatch.undo()

    delete_root = tmp_path / "delete"
    delete_storage = LocalSemanticCandidateStorage(delete_root)
    delete_storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
    monkeypatch.setattr(Path, "unlink", lambda _self: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SemanticCandidateEvidenceError) as delete_error:
        delete_storage.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a")
    assert delete_error.value.retryable is True


class _ObjectStore:
    def __init__(self) -> None:
        self.payload = None
        self.failure = None
        self.deleted = False

    def _fail(self):
        if self.failure is not None:
            raise self.failure

    def put_immutable(self, **kwargs):
        self._fail()
        self.payload = kwargs["payload"]

    def get_bytes(self, **_kwargs):
        self._fail()
        return self.payload

    def head(self, _key):
        self._fail()
        return None if self.payload is None else {"size_bytes": len(self.payload)}

    def delete(self, _key):
        self._fail()
        self.payload = None
        self.deleted = True


def test_s3_candidate_storage_round_trip_missing_and_delete() -> None:
    store = _ObjectStore()
    storage = S3SemanticCandidateStorage(store)
    payload = _payload()
    metadata = semantic_candidate_payload_metadata(payload)
    assert storage.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is None
    assert storage.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is False
    assert storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a") == payload["storage_ref"]
    assert storage.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a") == _candidate()
    assert storage.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a") is True
    assert store.deleted is True


@pytest.mark.parametrize(("operation", "retryable"), [("save", True), ("load", False), ("delete", True)])
def test_s3_candidate_storage_sanitizes_object_store_failures(operation, retryable) -> None:
    store = _ObjectStore()
    storage = S3SemanticCandidateStorage(store)
    payload = _payload()
    metadata = semantic_candidate_payload_metadata(payload)
    if operation == "delete":
        store.payload = payload["content"].encode()
    store.failure = ObjectStorageError("PRIVATE", "secret detail", retryable=retryable)
    with pytest.raises(SemanticCandidateEvidenceError) as raised:
        if operation == "save":
            storage.save(payload, tenant_id="tenant-a", owner_subject_id="user-a")
        elif operation == "load":
            storage.load(metadata, tenant_id="tenant-a", owner_subject_id="user-a")
        else:
            storage.delete(metadata, tenant_id="tenant-a", owner_subject_id="user-a")
    assert raised.value.retryable is retryable
    assert "secret detail" not in raised.value.detail


def test_s3_key_and_default_storage_errors_are_normalized(monkeypatch) -> None:
    def fail_key(**_kwargs):
        raise ObjectStorageError("PRIVATE", "secret detail", retryable=True)

    monkeypatch.setattr(evidence_module, "build_owner_object_key", fail_key)
    with pytest.raises(SemanticCandidateEvidenceError) as key_error:
        S3SemanticCandidateStorage._key("tenant-a", "user-a", CANDIDATE_ID)
    assert key_error.value.retryable is True
    monkeypatch.undo()

    store = _ObjectStore()
    monkeypatch.setattr(evidence_module, "build_ae_private_object_store", lambda _env: store)
    selected = build_default_semantic_candidate_storage(
        {"NEX_AE_PRIVATE_STORAGE_MODE": "S3"}
    )
    assert isinstance(selected, S3SemanticCandidateStorage)

    def fail_mode(_env):
        from nex_ae_api.private_object_store import AePrivateObjectStorageError

        raise AePrivateObjectStorageError("PRIVATE_MODE_INVALID", "private detail", True)

    monkeypatch.setattr(evidence_module, "ae_private_storage_mode", fail_mode)
    with pytest.raises(SemanticCandidateEvidenceError) as mode_error:
        build_default_semantic_candidate_storage({})
    assert mode_error.value.error_code == "PRIVATE_MODE_INVALID"
    assert mode_error.value.retryable is True


def _raw_payload(content: str) -> dict:
    encoded = content.encode()
    digest = __import__("hashlib").sha256(encoded).hexdigest()
    return {
        "candidate_id": CANDIDATE_ID,
        "content": content,
        "content_sha256": digest,
        "size_bytes": len(encoded),
        "storage_ref": f"ae://semantic-candidates/{CANDIDATE_ID}/{digest}.json",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**_payload(), "extra": True},
        {**_payload(), "candidate_id": "bad"},
        {**_payload(), "content_sha256": "bad"},
        {**_payload(), "size_bytes": True},
        {**_payload(), "storage_ref": "bad"},
        {**_payload(), "content": 1},
        _raw_payload("{"),
        _raw_payload("[]"),
        _raw_payload('{"value": 1}'),
    ],
)
def test_payload_validation_rejects_shape_and_content_drift(payload) -> None:
    with pytest.raises(SemanticCandidateEvidenceError):
        semantic_candidate_payload_metadata(payload)


def test_payload_builder_and_decoder_boundaries() -> None:
    with pytest.raises(SemanticCandidateEvidenceError):
        build_semantic_candidate_payload(candidate_id=CANDIDATE_ID, candidate={"x": object()})
    with pytest.raises(SemanticCandidateEvidenceError):
        build_semantic_candidate_payload(
            candidate_id=CANDIDATE_ID,
            candidate={"x": "x" * evidence_module.MAX_SEMANTIC_CANDIDATE_BYTES},
        )

    payload = b"\xff"
    digest = __import__("hashlib").sha256(payload).hexdigest()
    with pytest.raises(SemanticCandidateEvidenceError):
        evidence_module._decode_candidate(
            payload, {"content_sha256": digest, "size_bytes": 1}
        )

    sequence_payload = b"[]"
    sequence_digest = __import__("hashlib").sha256(sequence_payload).hexdigest()
    with pytest.raises(SemanticCandidateEvidenceError):
        evidence_module._decode_candidate(
            sequence_payload,
            {"content_sha256": sequence_digest, "size_bytes": 2},
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "tenant_id": ""},
        lambda value: {**value, "candidate_id": 1},
        lambda value: {**value, "execution_id": "bad"},
        lambda value: {**value, "semantic_stage": "OTHER"},
        lambda value: {**value, "candidate_revision": 0},
        lambda value: {**value, "candidate_hash": "bad"},
        lambda value: {**value, "candidate_payload_size_bytes": True},
        lambda value: {**value, "provider_output_sha256": "bad"},
        lambda value: {**value, "input_context_hash": "bad"},
        lambda value: {**value, "prompt_binding_id": "bad"},
        lambda value: {**value, "prompt_binding_key": ""},
        lambda value: {**value, "validation_outcome": "OTHER"},
        lambda value: {**value, "failure_code": "bad-code"},
        lambda value: {**value, "created_at": 1},
        lambda value: {**value, "created_at": "not-a-time"},
        lambda value: {**value, "created_at": "2026-10-17T01:00:00"},
    ],
)
def test_evidence_validation_rejects_field_boundary_drift(mutation) -> None:
    with pytest.raises(SemanticCandidateEvidenceError):
        validate_semantic_candidate_evidence(mutation(_evidence()))


def test_failed_evidence_without_payload_has_no_payload_metadata() -> None:
    value = {
        **_evidence(),
        "candidate_hash": None,
        "candidate_payload_storage_ref": None,
        "candidate_payload_size_bytes": None,
        "validation_outcome": "FAILED",
        "directive": "BLOCKED",
        "failure_code": "PROVIDER_FAILED",
    }
    with pytest.raises(SemanticCandidateEvidenceError) as raised:
        candidate_payload_metadata_from_evidence(value)
    assert "no persisted payload" in raised.value.detail


def test_repository_save_unavailable_and_write_conflict_are_fail_closed(monkeypatch) -> None:
    empty = sessionmaker(bind=create_engine("sqlite+pysqlite://", future=True))
    with pytest.raises(SemanticCandidateEvidenceError) as unavailable:
        SqlAlchemySemanticCandidateEvidenceRepository(empty).save(_evidence())
    assert unavailable.value.retryable is True

    repository = SqlAlchemySemanticCandidateEvidenceRepository(_factory())
    monkeypatch.setattr(evidence_module, "_load_evidence", lambda *_args: None)
    monkeypatch.setattr(evidence_module, "_load_stage_evidence", lambda *_args: None)
    with pytest.raises(SemanticCandidateEvidenceError) as conflict:
        repository.save(_evidence())
    assert conflict.value.error_code == "ae.semantic_candidate_write_conflict"
    assert conflict.value.retryable is True


@pytest.mark.parametrize("value", [{"key": "value"}, '{"key":"value"}'])
def test_stored_json_object_accepts_mapping_and_json_object(value) -> None:
    assert evidence_module._json_object(value) == {"key": "value"}


@pytest.mark.parametrize("value", ["[]", "not-json", 1])
def test_stored_json_object_rejects_invalid_values(value) -> None:
    with pytest.raises(SemanticCandidateEvidenceError):
        evidence_module._json_object(value)


def test_evidence_canonicalization_and_storage_ref_helpers_fail_closed() -> None:
    with pytest.raises(SemanticCandidateEvidenceError):
        validate_semantic_candidate_evidence({"bad": object()})
    for value in (1, "bad"):
        with pytest.raises(SemanticCandidateEvidenceError):
            evidence_module._storage_ref_relative_path(value)
