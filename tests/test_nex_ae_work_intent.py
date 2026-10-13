from __future__ import annotations

import copy
import json
from pathlib import Path

import nex_ae_api.work_intent as module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.intent_policy import resolve_intent_decision
from nex_ae_api.work_intent import (
    SqlAlchemyWorkIntentRepository,
    WorkIntentError,
    build_work_intent_from_decision,
    planning_mode,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/transition/P5/contracts/p5-work-intent-v1.1.schema.json"
TENANT = "tenant-p5"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222222"
REVISION_ID = "33333333-3333-4333-8333-333333333333"
PROMPT_VERSION_ID = "44444444-4444-4444-8444-444444444444"
NOW = "2026-10-13T04:00:00Z"
CONTEXT_HASH = "sha256:" + "b" * 64


def _factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_work_intent (
                    tenant_id TEXT NOT NULL,
                    work_intent_id TEXT NOT NULL,
                    intent_revision INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    supersedes_work_intent_id TEXT,
                    source_ref TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    compatibility_execution_mode TEXT NOT NULL,
                    work_class TEXT NOT NULL,
                    intent_hash TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, work_intent_id),
                    UNIQUE (tenant_id, agent_execution_id, intent_revision)
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _intent(*, mode: str = "GROUNDED_ANSWER", **overrides):
    decision = resolve_intent_decision(
        {
            "user_message": "private user prompt that must not be copied",
            "generation": {"execution_mode": mode},
        }
    )
    values = {
        "execution_id": EXECUTION_ID,
        "source_ref": "AE:INTERACTION:interaction-1",
        "actor_ref": "OA:SUBJECT:employee-100",
        "received_at": NOW,
        "intent_decision": decision,
        "input_context_hash": CONTEXT_HASH,
        "work_intent_id": WORK_INTENT_ID,
    }
    return build_work_intent_from_decision(**{**values, **overrides})


def _validate(value: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(value)


@pytest.mark.parametrize(
    ("mode", "work_class", "criterion_fragment"),
    [
        ("GENERAL_ANSWER", "QUERY", "direct response"),
        ("GROUNDED_ANSWER", "QUERY", "grounded response"),
        ("DOCUMENT_SUMMARY", "ANALYSIS", "source-traceable summary"),
        ("DOCUMENT_GENERATION", "DOCUMENT", "structured document"),
    ],
)
def test_intent_decision_adapter_builds_contract_valid_prompt_private_work_intent(
    mode: str, work_class: str, criterion_fragment: str
) -> None:
    record = _intent(mode=mode)

    _validate(record)
    assert record["execution_mode"] == "INTERACTIVE"
    assert record["compatibility_execution_mode"] == mode
    assert record["work_class"] == work_class
    assert criterion_fragment in record["completion_criteria"][0]["description"]
    assert record["required_capability_hints"] == ["AE.CHAT.COMPATIBILITY"]
    assert "private user prompt" not in json.dumps(record, ensure_ascii=False)
    assert record["provenance"]["intent_decision_hash"] == resolve_intent_decision(
        {
            "user_message": "private user prompt that must not be copied",
            "generation": {"execution_mode": mode},
        }
    )["decision_hash"]


def test_adapter_captures_complete_exact_prompt_provenance() -> None:
    record = _intent(
        prompt_provenance={
            "prompt_binding_key": "ae.intent_resolution.default",
            "prompt_template_version_id": PROMPT_VERSION_ID,
            "prompt_content_sha256": "c" * 64,
            "rendered_prompt_hash": "d" * 64,
            "model_profile": "generation-default",
            "model_ref": "provider/model@revision",
        }
    )

    _validate(record)
    assert record["provenance"]["resolver_type"] == "LLM_CANDIDATE"
    assert record["provenance"]["prompt_template_version_id"] == PROMPT_VERSION_ID


def test_work_intent_repository_is_immutable_idempotent_and_revisioned() -> None:
    factory = _factory()
    repository = SqlAlchemyWorkIntentRepository(factory)
    first = _intent()

    assert repository.save(
        tenant_id=TENANT, work_intent=first, created_at=NOW
    ) == first
    assert repository.save(
        tenant_id=TENANT, work_intent=first, created_at=NOW
    ) == first
    assert repository.get(
        tenant_id=TENANT, work_intent_id=WORK_INTENT_ID
    ) == first

    revision = _intent(
        work_intent_id=REVISION_ID,
        intent_revision=2,
        supersedes_work_intent_id=WORK_INTENT_ID,
    )
    saved_revision = repository.save(
        tenant_id=TENANT, work_intent=revision, created_at=NOW
    )
    assert saved_revision["intent_revision"] == 2
    assert saved_revision["supersedes_work_intent_id"] == WORK_INTENT_ID
    assert repository.get(
        tenant_id=TENANT,
        work_intent_id="99999999-9999-4999-8999-999999999999",
    ) is None


def test_work_intent_repository_rejects_identity_revision_and_hash_conflicts() -> None:
    repository = SqlAlchemyWorkIntentRepository(_factory())
    first = _intent()
    repository.save(tenant_id=TENANT, work_intent=first, created_at=NOW)

    mutated = copy.deepcopy(first)
    mutated["goal"] = "Tampered"
    mutated["intent_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in mutated.items() if key != "intent_hash"}
    )
    with pytest.raises(WorkIntentError) as identity_conflict:
        repository.save(tenant_id=TENANT, work_intent=mutated, created_at=NOW)
    assert identity_conflict.value.error_code == "ae.work_intent_immutable_conflict"

    duplicate_revision = _intent(
        work_intent_id="55555555-5555-4555-8555-555555555555"
    )
    with pytest.raises(WorkIntentError) as revision_conflict:
        repository.save(
            tenant_id=TENANT, work_intent=duplicate_revision, created_at=NOW
        )
    assert revision_conflict.value.error_code == "ae.work_intent_revision_conflict"

    invalid_hash = copy.deepcopy(first)
    invalid_hash["intent_hash"] = "sha256:" + "0" * 64
    with pytest.raises(WorkIntentError) as hash_conflict:
        repository.save(tenant_id="other", work_intent=invalid_hash, created_at=NOW)
    assert hash_conflict.value.error_code == "ae.work_intent_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1.0"),
        ("source", {"source_type": "WORK_ITEM"}),
        ("execution_mode", "BATCH"),
        ("compatibility_execution_mode", "UNSUPPORTED"),
    ],
)
def test_repository_revalidates_work_intent_contract_fields(
    field: str, value: object
) -> None:
    repository = SqlAlchemyWorkIntentRepository(_factory())
    record = _intent()
    record[field] = value
    record["intent_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "intent_hash"}
    )

    with pytest.raises(WorkIntentError) as raised:
        repository.save(tenant_id=TENANT, work_intent=record, created_at=NOW)

    assert raised.value.error_code == "ae.work_intent_invalid"


def test_repository_reports_unreadable_insert_without_revision_owner(
    monkeypatch,
) -> None:
    repository = SqlAlchemyWorkIntentRepository(_factory())
    monkeypatch.setattr(module, "_load_work_intent", lambda *args: None)
    monkeypatch.setattr(module, "_load_work_intent_by_revision", lambda *args: None)

    with pytest.raises(WorkIntentError) as raised:
        repository.save(tenant_id=TENANT, work_intent=_intent(), created_at=NOW)

    assert raised.value.error_code == "ae.work_intent_write_conflict"
    assert raised.value.retryable is True


def test_work_intent_revision_chain_must_be_contiguous_and_same_execution() -> None:
    repository = SqlAlchemyWorkIntentRepository(_factory())
    first = _intent()
    repository.save(tenant_id=TENANT, work_intent=first, created_at=NOW)

    revision = _intent(
        work_intent_id=REVISION_ID,
        intent_revision=2,
        supersedes_work_intent_id="99999999-9999-4999-8999-999999999999",
    )
    with pytest.raises(WorkIntentError) as raised:
        repository.save(tenant_id=TENANT, work_intent=revision, created_at=NOW)
    assert raised.value.error_code == "ae.work_intent_revision_chain_invalid"


def test_planning_mode_is_fail_closed_and_defaults_to_disabled() -> None:
    assert planning_mode({}) == "disabled"
    assert planning_mode({"NEX_AE_PLANNING_MODE": " SHADOW "}) == "shadow"
    assert planning_mode({"NEX_AE_PLANNING_MODE": "required"}) == "required"
    with pytest.raises(WorkIntentError) as raised:
        planning_mode({"NEX_AE_PLANNING_MODE": "unsafe"})
    assert raised.value.error_code == "ae.work_intent_invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values.update(execution_id=None),
        lambda values: values.update(execution_id="not-a-uuid"),
        lambda values: values.update(source_ref=""),
        lambda values: values.update(received_at=None),
        lambda values: values.update(received_at="not-a-date"),
        lambda values: values.update(received_at="2026-10-13T04:00:00"),
        lambda values: values.update(input_context_hash="b" * 64),
        lambda values: values.update(intent_revision=0),
        lambda values: values.update(intent_revision=2),
        lambda values: values.update(
            supersedes_work_intent_id=REVISION_ID
        ),
        lambda values: values["intent_decision"].update(
            intent_decision_schema_version="unsupported"
        ),
        lambda values: values["intent_decision"].update(
            execution_mode="UNSUPPORTED"
        ),
        lambda values: values["intent_decision"].update(raw_prompt_included=True),
        lambda values: values["intent_decision"].update(confidence=True),
        lambda values: values["intent_decision"].update(confidence=2),
        lambda values: values.update(
            prompt_provenance={"prompt_binding_key": "incomplete"}
        ),
    ],
)
def test_adapter_rejects_invalid_or_ambiguous_inputs(mutation) -> None:
    decision = resolve_intent_decision({"user_message": "hello"})
    values = {
        "execution_id": EXECUTION_ID,
        "source_ref": "interaction-1",
        "actor_ref": "employee-100",
        "received_at": NOW,
        "intent_decision": decision,
        "input_context_hash": CONTEXT_HASH,
        "work_intent_id": WORK_INTENT_ID,
    }
    mutation(values)
    with pytest.raises((WorkIntentError, ValueError)):
        build_work_intent_from_decision(**values)


def test_repository_wraps_database_errors_and_error_string() -> None:
    repository = SqlAlchemyWorkIntentRepository(_factory(with_schema=False))
    record = _intent()
    with pytest.raises(WorkIntentError) as write_error:
        repository.save(tenant_id=TENANT, work_intent=record, created_at=NOW)
    assert write_error.value.error_code == "ae.work_intent_store_unavailable"
    assert write_error.value.retryable is True
    assert str(write_error.value) == "AE WorkIntent store is unavailable."

    with pytest.raises(WorkIntentError) as read_error:
        repository.get(tenant_id=TENANT, work_intent_id=WORK_INTENT_ID)
    assert read_error.value.error_code == "ae.work_intent_store_unavailable"


def test_postgres_insert_uses_jsonb_cast() -> None:
    assert "CAST(:intent_json AS jsonb)" in module._intent_insert_sql("postgresql")
