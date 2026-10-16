from __future__ import annotations

import copy
import json
from pathlib import Path

import nex_ae_api.agent_context as module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.agent_context import (
    AgentContextError,
    ContextCandidateHints,
    SqlAlchemyAgentContextRepository,
    TrustedContextResolution,
    build_agent_context,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.intent_policy import resolve_intent_decision
from nex_ae_api.runtime_policy import resolve_runtime_policy
from nex_ae_api.work_intent import build_work_intent_from_decision
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/transition/P5/contracts/p5-agent-context-v1.1.schema.json"
TENANT = "tenant-p5"
PRINCIPAL = "employee-100"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
AGENT_ID = "44444444-4444-4444-8444-444444444444"
WORKSPACE_ID = "55555555-5555-4555-8555-555555555555"
CONVERSATION_ID = "66666666-6666-4666-8666-666666666666"
INTERACTION_ID = "77777777-7777-4777-8777-777777777777"
NOW = "2026-10-13T08:00:00Z"
HASH_A = "sha256:" + "a" * 64


class Resolver:
    def __init__(self, resolution: TrustedContextResolution | object) -> None:
        self.resolution = resolution
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return self.resolution


def _resolution(**overrides) -> TrustedContextResolution:
    values = {
        "project_ref": None,
        "authority_ref": "OA:EAC:decision-1",
        "resolved_entities": (),
        "retrieval_refs": (
            {
                "system": "CX",
                "resource_type": "RETRIEVAL_PACKAGE",
                "resource_id": "retrieval-1",
                "version": "1",
            },
        ),
        "evidence_refs": (),
        "conflicts": (),
        "degradations": (),
        "context_manifest": (
            {
                "kind": "INTERACTION_REF",
                "source_ref": f"AE:INTERACTION:{INTERACTION_ID}",
                "source_version": "1",
                "content_hash": HASH_A,
                "as_of": NOW,
            },
        ),
        "budget_tokens": 4096,
        "estimated_used_tokens": 128,
        "truncated_optional_items": 0,
    }
    return TrustedContextResolution(**{**values, **overrides})


def _work_intent() -> dict:
    decision = resolve_intent_decision(
        {
            "user_message": "private prompt must stay outside AgentContext",
            "generation": {"execution_mode": "GROUNDED_ANSWER"},
        }
    )
    return build_work_intent_from_decision(
        execution_id=EXECUTION_ID,
        source_ref=f"AE:INTERACTION:{INTERACTION_ID}",
        actor_ref=f"OA:SUBJECT:{PRINCIPAL}",
        received_at=NOW,
        intent_decision=decision,
        input_context_hash=HASH_A,
        work_intent_id=WORK_INTENT_ID,
    )


def _policy_ref() -> dict:
    policy = resolve_runtime_policy({"user_message": "hello"})
    return runtime_policy_ref_from_compatibility_policy(policy)


def _context(*, resolver=None, **overrides) -> dict:
    values = {
        "tenant_id": TENANT,
        "principal_id": PRINCIPAL,
        "agent_id": AGENT_ID,
        "execution_id": EXECUTION_ID,
        "workspace_id": WORKSPACE_ID,
        "conversation_id": CONVERSATION_ID,
        "interaction_id": INTERACTION_ID,
        "work_intent": _work_intent(),
        "runtime_policy_ref": _policy_ref(),
        "resolver": resolver or Resolver(_resolution()),
        "context_id": CONTEXT_ID,
        "built_at": NOW,
    }
    return build_agent_context(**{**values, **overrides})


def _factory(*, with_schema: bool = True, seed_lineage: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    workspace_id TEXT,
                    conversation_id TEXT,
                    legacy_interaction_id TEXT,
                    PRIMARY KEY (tenant_id, agent_execution_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_work_intent (
                    tenant_id TEXT NOT NULL,
                    work_intent_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    intent_revision INTEGER NOT NULL,
                    intent_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, work_intent_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_context (
                    tenant_id TEXT NOT NULL,
                    context_id TEXT NOT NULL,
                    context_generation INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    work_intent_id TEXT NOT NULL,
                    work_intent_revision INTEGER NOT NULL,
                    work_intent_hash TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    built_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, context_id),
                    UNIQUE (tenant_id, agent_execution_id, context_generation)
                )
            """))
            if seed_lineage:
                intent = _work_intent()
                connection.execute(
                    text("""
                        INSERT INTO ae_agent_execution VALUES (
                            :tenant, :execution, :principal, :agent, 'IA',
                            :workspace, :conversation, :interaction
                        )
                    """),
                    {
                        "tenant": TENANT,
                        "execution": EXECUTION_ID,
                        "principal": PRINCIPAL,
                        "agent": AGENT_ID,
                        "workspace": WORKSPACE_ID,
                        "conversation": CONVERSATION_ID,
                        "interaction": INTERACTION_ID,
                    },
                )
                connection.execute(
                    text("""
                        INSERT INTO ae_work_intent VALUES (
                            :tenant, :intent, :execution, 1, :hash
                        )
                    """),
                    {
                        "tenant": TENANT,
                        "intent": WORK_INTENT_ID,
                        "execution": EXECUTION_ID,
                        "hash": intent["intent_hash"],
                    },
                )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _validate(value: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def test_builder_uses_trusted_resolver_and_builds_contract_valid_private_context() -> None:
    resolver = Resolver(
        _resolution(
            resolved_entities=(
                {
                    "selector_id": "E1",
                    "resource_ref": {
                        "system": "OA",
                        "resource_type": "SUBJECT",
                        "resource_id": PRINCIPAL,
                    },
                    "source_ref": "OA:SUBJECT_REGISTRY",
                    "resolved_at": NOW,
                },
            ),
            evidence_refs=(
                {
                    "system": "CX",
                    "resource_type": "CHUNK",
                    "resource_id": "chunk-1",
                },
            ),
        )
    )

    context = _context(resolver=resolver)

    _validate(context)
    assert len(resolver.requests) == 1
    assert resolver.requests[0].work_intent_ref["id"] == WORK_INTENT_ID
    assert context["identity"]["agent_type"] == "IA"
    assert context["project_ref"] is None
    assert context["context_hash"].startswith("sha256:")
    assert "private prompt" not in json.dumps(context, ensure_ascii=False)


def test_builder_passes_normalized_candidate_hints_only_to_trusted_resolver() -> None:
    source = {"candidate_key": "E1", "selector_value": "budget"}
    hints = ContextCandidateHints(
        candidate_hash=HASH_A,
        entity_candidates=(source,),
        retrieval_hints=(),
        resource_selectors=(),
        parameter_candidates=(),
        confidence=0.9,
    )
    resolver = Resolver(_resolution())

    context = _context(resolver=resolver, candidate_hints=hints)
    source["selector_value"] = "changed"

    assert resolver.requests[0].candidate_hints.entity_candidates[0][
        "selector_value"
    ] == "budget"
    assert "candidate_hints" not in context


@pytest.mark.parametrize(
    "hints",
    [
        "unsupported",
        ContextCandidateHints("bad", (), (), (), (), 0.9),
        ContextCandidateHints(HASH_A, (), (), (), (), True),
        ContextCandidateHints(HASH_A, [], (), (), (), 0.9),
        ContextCandidateHints(HASH_A, ("not-an-object",), (), (), (), 0.9),
        ContextCandidateHints(
            HASH_A,
            ({"candidate_key": "E1", "tenant_id": "invented"},),
            (),
            (),
            (),
            0.9,
        ),
        ContextCandidateHints(
            HASH_A,
            ({"candidate_key": "E1", "value": object()},),
            (),
            (),
            (),
            0.9,
        ),
    ],
)
def test_builder_rejects_invalid_or_authority_bearing_candidate_hints(hints) -> None:
    with pytest.raises(AgentContextError) as raised:
        _context(candidate_hints=hints)
    assert raised.value.error_code == "ae.agent_context_invalid"


def test_compatibility_policy_digest_conversion_does_not_rehash() -> None:
    policy = resolve_runtime_policy({"user_message": "hello"})
    bare = policy["compatibility_rule"]["rule_hash"]

    reference = runtime_policy_ref_from_compatibility_policy(policy)

    assert reference["rule_hash"] == f"sha256:{bare}"


def test_validator_accepts_resolved_entity_and_nullable_authority() -> None:
    context = _context(
        resolver=Resolver(
            _resolution(
                authority_ref=None,
                resolved_entities=(
                    {
                        "selector_id": "E1",
                        "resource_ref": {
                            "system": "OA",
                            "resource_type": "SUBJECT",
                            "resource_id": PRINCIPAL,
                        },
                        "source_ref": "OA:SUBJECT_REGISTRY",
                        "resolved_at": NOW,
                    },
                ),
            )
        )
    )

    assert module._validate_agent_context(context) == context


def test_repository_is_immutable_idempotent_restart_safe_and_generation_based() -> None:
    factory = _factory()
    repository = SqlAlchemyAgentContextRepository(factory)
    first = _context()

    assert repository.save(tenant_id=TENANT, agent_context=first) == first
    assert repository.save(tenant_id=TENANT, agent_context=first) == first
    assert SqlAlchemyAgentContextRepository(factory).get(
        tenant_id=TENANT, context_id=CONTEXT_ID
    ) == first

    second = _context(
        context_id="88888888-8888-4888-8888-888888888888",
        context_generation=2,
        resolver=Resolver(_resolution(degradations=("optional source unavailable",))),
    )
    assert repository.save(tenant_id=TENANT, agent_context=second) == second
    assert repository.get(
        tenant_id=TENANT,
        context_id="99999999-9999-4999-8999-999999999999",
    ) is None


def test_repository_rejects_immutable_generation_and_chain_conflicts() -> None:
    factory = _factory()
    repository = SqlAlchemyAgentContextRepository(factory)
    first = _context()
    repository.save(tenant_id=TENANT, agent_context=first)

    changed = copy.deepcopy(first)
    changed["degradations"] = ["changed"]
    changed["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed.items() if key != "context_hash"}
    )
    with pytest.raises(AgentContextError) as immutable:
        repository.save(tenant_id=TENANT, agent_context=changed)
    assert immutable.value.error_code == "ae.agent_context_immutable_conflict"

    duplicate = _context(context_id="88888888-8888-4888-8888-888888888888")
    with pytest.raises(AgentContextError) as generation:
        repository.save(tenant_id=TENANT, agent_context=duplicate)
    assert generation.value.error_code == "ae.agent_context_generation_conflict"

    without_first = SqlAlchemyAgentContextRepository(_factory())
    second = _context(
        context_id="88888888-8888-4888-8888-888888888888",
        context_generation=2,
    )
    with pytest.raises(AgentContextError) as chain:
        without_first.save(tenant_id=TENANT, agent_context=second)
    assert chain.value.error_code == "ae.agent_context_generation_chain_invalid"


@pytest.mark.parametrize(
    ("column", "value", "error_code"),
    [
        ("intent_hash", HASH_A, "ae.agent_context_work_intent_mismatch"),
        ("principal_id", "other", "ae.agent_context_execution_scope_mismatch"),
    ],
)
def test_repository_rejects_untrusted_persisted_lineage(
    column: str, value: str, error_code: str
) -> None:
    factory = _factory()
    table = "ae_work_intent" if column == "intent_hash" else "ae_agent_execution"
    with factory.begin() as session:
        session.execute(text(f"UPDATE {table} SET {column} = :value"), {"value": value})

    with pytest.raises(AgentContextError) as raised:
        SqlAlchemyAgentContextRepository(factory).save(
            tenant_id=TENANT, agent_context=_context()
        )

    assert raised.value.error_code == error_code


def test_repository_rejects_missing_execution_and_tenant_scope_mismatch() -> None:
    factory = _factory()
    with factory.begin() as session:
        session.execute(text("DELETE FROM ae_agent_execution"))
    with pytest.raises(AgentContextError) as missing:
        SqlAlchemyAgentContextRepository(factory).save(
            tenant_id=TENANT, agent_context=_context()
        )
    assert missing.value.error_code == "ae.agent_context_execution_not_found"

    with pytest.raises(AgentContextError) as tenant:
        SqlAlchemyAgentContextRepository(_factory()).save(
            tenant_id="other", agent_context=_context()
        )
    assert tenant.value.error_code == "ae.agent_context_invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values.update(agent_id="bad"),
        lambda values: values.update(execution_id="bad"),
        lambda values: values.update(context_generation=0),
        lambda values: values.update(built_at="not-a-date"),
        lambda values: values.update(resolver=Resolver(object())),
        lambda values: values.update(
            resolver=Resolver(_resolution(estimated_used_tokens=5000))
        ),
        lambda values: values.update(
            runtime_policy_ref={"rule_id": "x", "rule_version": "v1"}
        ),
    ],
)
def test_builder_fails_closed_for_invalid_inputs(mutation) -> None:
    values = {
        "tenant_id": TENANT,
        "principal_id": PRINCIPAL,
        "agent_id": AGENT_ID,
        "execution_id": EXECUTION_ID,
        "workspace_id": WORKSPACE_ID,
        "conversation_id": CONVERSATION_ID,
        "interaction_id": INTERACTION_ID,
        "work_intent": _work_intent(),
        "runtime_policy_ref": _policy_ref(),
        "resolver": Resolver(_resolution()),
        "context_id": CONTEXT_ID,
        "built_at": NOW,
    }
    mutation(values)
    with pytest.raises(AgentContextError):
        build_agent_context(**values)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version="1.0"),
        lambda value: value.update(unexpected=True),
        lambda value: value["identity"].update(agent_type="PA"),
        lambda value: value["interaction"].update(workspace_id="bad"),
        lambda value: value.update(context_hash=HASH_A),
        lambda value: value["budget"].update(estimated_used_tokens=5000),
    ],
)
def test_repository_revalidates_contract_and_semantic_hash(mutation) -> None:
    value = _context()
    mutation(value)
    if value.get("context_hash") != HASH_A:
        value["context_hash"] = semantic_sha256_hash_ref(
            {key: item for key, item in value.items() if key != "context_hash"}
        )
    with pytest.raises(AgentContextError) as raised:
        SqlAlchemyAgentContextRepository(_factory()).save(
            tenant_id=TENANT, agent_context=value
        )
    assert raised.value.error_code == "ae.agent_context_invalid"


def test_private_material_and_invalid_compatibility_policy_are_rejected() -> None:
    with pytest.raises(AgentContextError):
        module._reject_private_material(
            {"nested": [{"raw_prompt": "secret"}]}
        )
    with pytest.raises(AgentContextError):
        runtime_policy_ref_from_compatibility_policy({})
    with pytest.raises(AgentContextError):
        runtime_policy_ref_from_compatibility_policy(
            {
                "compatibility_rule": {
                    "rule_id": "x",
                    "rule_version": "v1",
                    "rule_hash": "bad",
                }
            }
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(interaction=None),
        lambda value: value.update(retrieval_refs="not-an-array"),
        lambda value: value.update(budget=None),
        lambda value: value.update(context_hash="bad"),
        lambda value: value.update(context_id=WORK_INTENT_ID),
        lambda value: value["work_intent_ref"].update(hash="bad"),
        lambda value: value["runtime_policy_ref"].update(rule_hash="bad"),
        lambda value: value.update(conflicts="not-an-array"),
        lambda value: value.update(conflicts=["x"] * 33),
        lambda value: value.update(context_generation=10000),
        lambda value: value.update(built_at=None),
        lambda value: value.update(built_at="2026-10-13T08:00:00"),
    ],
)
def test_validator_covers_bounded_shape_failure_paths(mutation) -> None:
    value = _context()
    mutation(value)
    if value.get("context_hash") not in {"bad", HASH_A}:
        value["context_hash"] = semantic_sha256_hash_ref(
            {key: item for key, item in value.items() if key != "context_hash"}
        )

    with pytest.raises(AgentContextError):
        module._validate_agent_context(value)


@pytest.mark.parametrize(
    "call",
    [
        lambda: module._validate_agent_context({"value": float("nan")}),
        lambda: module._versioned_hash_ref("ref", None),
        lambda: module._resource_ref("not-a-ref"),
        lambda: module._resource_ref({"system": "CX"}),
        lambda: module._resolved_entity(None),
        lambda: module._resolved_entity(
            {
                "selector_id": "bad",
                "resource_ref": {
                    "system": "CX",
                    "resource_type": "DOCUMENT",
                    "resource_id": "1",
                },
                "source_ref": "CX:INDEX",
                "resolved_at": NOW,
            }
        ),
        lambda: module._manifest_entry(None),
        lambda: module._manifest_entry({"kind": "INTERACTION_REF"}),
        lambda: module._manifest_entry(
            {
                "kind": "INTERACTION_REF",
                "source_ref": "AE:INTERACTION:1",
                "content_hash": "bad",
                "as_of": NOW,
            }
        ),
        lambda: module._required_uuid("id", None),
        lambda: module._required_text("name", None, maximum=10),
        lambda: module._required_datetime("at", None),
    ],
)
def test_validation_helpers_fail_closed(call) -> None:
    with pytest.raises(AgentContextError):
        call()


def test_builder_rejects_work_intent_from_another_execution() -> None:
    intent = _work_intent()
    intent["execution_id"] = "88888888-8888-4888-8888-888888888888"

    with pytest.raises(AgentContextError) as raised:
        _context(work_intent=intent)

    assert raised.value.error_code == "ae.agent_context_invalid"


def test_repository_wraps_database_errors_and_unreadable_insert(monkeypatch) -> None:
    repository = SqlAlchemyAgentContextRepository(_factory(with_schema=False))
    with pytest.raises(AgentContextError) as write_error:
        repository.save(tenant_id=TENANT, agent_context=_context())
    assert write_error.value.error_code == "ae.agent_context_store_unavailable"
    assert write_error.value.retryable is True
    assert str(write_error.value) == "AE AgentContext store is unavailable."
    with pytest.raises(AgentContextError) as read_error:
        repository.get(tenant_id=TENANT, context_id=CONTEXT_ID)
    assert read_error.value.error_code == "ae.agent_context_store_unavailable"

    repository = SqlAlchemyAgentContextRepository(_factory())
    monkeypatch.setattr(module, "_load_context", lambda *args: None)
    monkeypatch.setattr(module, "_load_context_by_generation", lambda *args: None)
    with pytest.raises(AgentContextError) as conflict:
        repository.save(tenant_id=TENANT, agent_context=_context())
    assert conflict.value.error_code == "ae.agent_context_write_conflict"


def test_postgres_insert_uses_jsonb_cast() -> None:
    assert "CAST(:context_json AS jsonb)" in module._context_insert_sql("postgresql")
