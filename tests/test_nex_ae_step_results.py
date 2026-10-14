from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api import step_results
from nex_ae_api.step_results import (
    SqlAlchemyStepResultRepository,
    StepResultError,
    build_step_result,
    validate_step_result_contract,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/transition/P5/contracts/p5-step-result-v1.1.schema.json"
TENANT = "tenant-p5-s6"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
PLAN_ID = "22222222-2222-4222-8222-222222222222"
STEP_ID = "33333333-3333-4333-8333-333333333333"
RESULT_ID = "44444444-4444-4444-8444-444444444444"
NOW = "2026-10-14T09:00:00Z"
LATER = "2026-10-14T09:00:01Z"


def _result(**overrides):
    values = {
        "step_result_id": RESULT_ID,
        "execution_id": EXECUTION_ID,
        "executable_plan_id": PLAN_ID,
        "executable_step_id": STEP_ID,
        "compiled_step_key": "E1",
        "logical_step_ref": "S1",
        "attempt_no": 1,
        "status": "SUCCEEDED",
        "result_contract_ref": "contract://nex/ae/chat-result/v1",
        "result_payload": {"result_ref": "AE:CHAT:1"},
        "external_refs": ("CX:GENERATION:1",),
        "artifact_refs": (),
        "evidence_refs": ("CX:RETRIEVAL:1",),
        "started_at": NOW,
        "completed_at": LATER,
    }
    return build_step_result(**{**values, **overrides})


def _factory(*, schema=True, seed=True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if schema:
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE ae_executable_step (
                        tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                        agent_execution_id TEXT NOT NULL, executable_plan_id TEXT,
                        compiled_step_key TEXT, logical_step_id TEXT, state TEXT NOT NULL,
                        executor_kind TEXT,
                        PRIMARY KEY (tenant_id, executable_step_id))"""))
            connection.execute(text("""CREATE TABLE ae_step_result (
                        tenant_id TEXT NOT NULL, step_result_id TEXT NOT NULL,
                        agent_execution_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                        executable_step_id TEXT NOT NULL, compiled_step_key TEXT NOT NULL,
                        logical_step_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                        status TEXT NOT NULL, result_contract_ref TEXT NOT NULL,
                        result_payload TEXT NOT NULL, external_refs TEXT NOT NULL,
                        artifact_refs TEXT NOT NULL, evidence_refs TEXT NOT NULL,
                        error_ref TEXT, business_operation_id TEXT,
                        operation_fingerprint TEXT, executor_kind TEXT,
                        started_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL, result_hash TEXT NOT NULL,
                        result_json TEXT NOT NULL, created_at TEXT,
                        PRIMARY KEY (tenant_id, step_result_id),
                        UNIQUE (tenant_id, executable_step_id))"""))
            if seed:
                connection.execute(
                    text(
                        "INSERT INTO ae_executable_step VALUES "
                        "(:t, :s, :e, :p, 'E1', 'S1', 'SUCCEEDED', "
                        "'P4_CHAT_RAG_COMPATIBILITY')"
                    ),
                    {"t": TENANT, "s": STEP_ID, "e": EXECUTION_ID, "p": PLAN_ID},
                )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_builder_emits_schema_valid_immutable_result_with_null_write_identity() -> None:
    result = _result()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)

    assert result["business_operation_id"] is None
    assert result["operation_fingerprint"] is None
    assert result["result_hash"].startswith("sha256:")
    assert result["external_refs"] == ["CX:GENERATION:1"]


def test_semantic_hash_excludes_generated_identity_and_timestamps() -> None:
    first = _result()
    second = _result(
        step_result_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        started_at="2026-10-14T10:00:00Z",
        completed_at="2026-10-14T10:00:03Z",
    )

    assert first["step_result_id"] != second["step_result_id"]
    assert first["result_hash"] == second["result_hash"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"compiled_step_key": "S1"},
        {"logical_step_ref": "E1"},
        {"attempt_no": 0},
        {"status": "WAITING"},
        {"result_payload": []},
        {"external_refs": ("dup", "dup")},
        {"completed_at": "2026-10-14T08:59:59Z"},
    ],
)
def test_builder_rejects_invalid_terminal_contract(overrides) -> None:
    with pytest.raises(StepResultError):
        _result(**overrides)


def test_validator_rejects_write_identity_and_hash_tampering() -> None:
    changed = _result()
    changed["business_operation_id"] = "forbidden"
    with pytest.raises(StepResultError, match="WRITE identity"):
        validate_step_result_contract(changed)

    changed = _result()
    changed["result_payload"] = {"changed": True}
    with pytest.raises(StepResultError, match="hash"):
        validate_step_result_contract(changed)

    with pytest.raises(StepResultError, match="fields"):
        validate_step_result_contract({})


def test_repository_is_idempotent_and_restart_safe() -> None:
    factory = _factory()
    repository = SqlAlchemyStepResultRepository(factory)
    result = _result()

    assert repository.save(tenant_id=TENANT, step_result=result) == result
    assert repository.save(tenant_id=TENANT, step_result=result) == result
    restarted = SqlAlchemyStepResultRepository(factory)
    assert restarted.get(tenant_id=TENANT, step_result_id=RESULT_ID) == result
    assert restarted.get_by_step(tenant_id=TENANT, executable_step_id=STEP_ID) == result
    assert restarted.list_for_plan(tenant_id=TENANT, executable_plan_id=PLAN_ID) == [
        result
    ]


def test_repository_rejects_lineage_and_immutable_conflicts() -> None:
    factory = _factory()
    repository = SqlAlchemyStepResultRepository(factory)
    result = _result()
    with factory.begin() as session:
        session.execute(text("UPDATE ae_executable_step SET state = 'FAILED'"))
    with pytest.raises(StepResultError) as exc_info:
        repository.save(tenant_id=TENANT, step_result=result)
    assert exc_info.value.error_code == "ae.step_result_lineage_mismatch"

    with factory.begin() as session:
        session.execute(text("UPDATE ae_executable_step SET state = 'SUCCEEDED'"))
    repository.save(tenant_id=TENANT, step_result=result)
    changed = copy.deepcopy(result)
    changed["step_result_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with pytest.raises(StepResultError) as exc_info:
        repository.save(tenant_id=TENANT, step_result=changed)
    assert exc_info.value.error_code == "ae.step_result_step_conflict"


def test_repository_maps_store_failures() -> None:
    repository = SqlAlchemyStepResultRepository(_factory(schema=False))
    with pytest.raises(StepResultError) as exc_info:
        repository.save(tenant_id=TENANT, step_result=_result())
    assert exc_info.value.error_code == "ae.step_result_store_unavailable"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step_result_id", None),
        ("execution_id", "not-a-uuid"),
        ("result_contract_ref", ""),
        ("result_contract_ref", "x" * 257),
        ("error_ref", "x" * 257),
        ("started_at", ""),
        ("started_at", "not-a-time"),
        ("started_at", "2026-10-14T09:00:00"),
        ("external_refs", "not-an-array"),
        ("artifact_refs", tuple(str(index) for index in range(65))),
    ],
)
def test_builder_rejects_primitive_boundary_violations(field, value) -> None:
    with pytest.raises(StepResultError, match="must|bounded"):
        _result(**{field: value})


def test_builder_normalizes_sorted_references_and_timezone() -> None:
    result = _result(
        external_refs=("ref:z", "ref:a"),
        started_at="2026-10-14T18:00:00+09:00",
        completed_at="2026-10-14T18:00:01+09:00",
    )

    assert result["external_refs"] == ["ref:a", "ref:z"]
    assert result["started_at"] == NOW
    assert result["completed_at"] == LATER


def test_validator_rejects_noncanonical_invalid_hash_and_time_order() -> None:
    changed = _result()
    changed["result_payload"] = {"bad": {"set"}}
    with pytest.raises(StepResultError, match="canonical JSON"):
        validate_step_result_contract(changed)
    with pytest.raises(StepResultError, match="result_payload must be canonical JSON"):
        step_results._mapping("result_payload", {"bad": {"set"}})

    changed = _result()
    changed["result_hash"] = "not-a-hash"
    with pytest.raises(StepResultError, match="result_hash is invalid"):
        validate_step_result_contract(changed)

    changed = _result()
    changed["completed_at"] = "2026-10-14T08:59:59Z"
    with pytest.raises(StepResultError, match="precedes"):
        validate_step_result_contract(changed)

    changed = _result()
    changed["extra"] = True
    with pytest.raises(StepResultError, match="fields"):
        validate_step_result_contract(changed)


def test_repository_rejects_missing_step_and_corrupt_stored_result() -> None:
    factory = _factory(seed=False)
    repository = SqlAlchemyStepResultRepository(factory)
    with pytest.raises(StepResultError) as exc_info:
        repository.save(tenant_id=TENANT, step_result=_result())
    assert exc_info.value.error_code == "ae.step_result_step_not_found"

    factory = _factory()
    repository = SqlAlchemyStepResultRepository(factory)
    repository.save(tenant_id=TENANT, step_result=_result())
    with factory.begin() as session:
        session.execute(
            text("UPDATE ae_step_result SET result_json = '[]' WHERE tenant_id = :t"),
            {"t": TENANT},
        )
    with pytest.raises(StepResultError) as exc_info:
        repository.get(tenant_id=TENANT, step_result_id=RESULT_ID)
    assert exc_info.value.error_code == "ae.step_result_corrupt"


def test_repository_maps_all_read_store_failures() -> None:
    repository = SqlAlchemyStepResultRepository(_factory(schema=False))

    for action in (
        lambda: repository.get(tenant_id=TENANT, step_result_id=RESULT_ID),
        lambda: repository.get_by_step(tenant_id=TENANT, executable_step_id=STEP_ID),
        lambda: repository.list_for_plan(tenant_id=TENANT, executable_plan_id=PLAN_ID),
    ):
        with pytest.raises(StepResultError) as exc_info:
            action()
        assert exc_info.value.error_code == "ae.step_result_store_unavailable"


class _InsertResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _PersistenceSession:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount

    def execute(self, *_args, **_kwargs):
        return _InsertResult(self.rowcount)

    def get_bind(self):
        return type(
            "Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()}
        )()


def test_persistence_detects_reload_and_unique_step_conflicts(monkeypatch) -> None:
    result = _result()
    session = _PersistenceSession()
    monkeypatch.setattr(step_results, "load_step_result_by_id", lambda *a: None)
    monkeypatch.setattr(
        step_results, "load_step_result_by_step", lambda *a: {"conflict": True}
    )
    with pytest.raises(StepResultError) as exc_info:
        step_results.persist_step_result_in_session(session, TENANT, result)
    assert exc_info.value.error_code == "ae.step_result_step_conflict"

    monkeypatch.setattr(step_results, "load_step_result_by_step", lambda *a: None)
    with pytest.raises(StepResultError) as exc_info:
        step_results.persist_step_result_in_session(session, TENANT, result)
    assert exc_info.value.error_code == "ae.step_result_write_conflict"
    assert exc_info.value.retryable is True


def test_persistence_detects_immutable_and_zero_row_conflicts(monkeypatch) -> None:
    result = _result()
    changed = copy.deepcopy(result)
    changed["result_payload"] = {"changed": True}
    monkeypatch.setattr(step_results, "load_step_result_by_id", lambda *a: changed)
    with pytest.raises(StepResultError) as exc_info:
        step_results.persist_step_result_in_session(
            _PersistenceSession(), TENANT, result
        )
    assert exc_info.value.error_code == "ae.step_result_immutable_conflict"

    monkeypatch.setattr(step_results, "load_step_result_by_id", lambda *a: result)
    monkeypatch.setattr(step_results, "load_step_result_by_step", lambda *a: changed)
    with pytest.raises(StepResultError) as exc_info:
        step_results.persist_step_result_in_session(
            _PersistenceSession(rowcount=0), TENANT, result
        )
    assert exc_info.value.error_code == "ae.step_result_step_conflict"


def test_postgres_insert_shape_uses_jsonb_casts() -> None:
    sql = step_results._insert_sql("postgresql")

    assert sql.count("AS JSONB") == 5
