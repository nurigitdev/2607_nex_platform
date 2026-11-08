from __future__ import annotations

import json
from pathlib import Path

import nex_ae_api.agent_plans as module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.agent_plans import (
    AgentPlanError,
    SqlAlchemyAgentPlanRepository,
    build_deterministic_agent_plan,
)
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    SqlAlchemyCapabilitySnapshotRepository,
    build_capability_snapshot,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/transition/P5/contracts/p5-agent-plan-v1.1.schema.json"
TENANT = "tenant-p5"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
SNAPSHOT_ID = "44444444-4444-4444-8444-444444444444"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
OTHER_PLAN_ID = "66666666-6666-4666-8666-666666666666"
NOW = "2026-10-13T09:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _work_intent(mode="GROUNDED_ANSWER"):
    value = {
        "work_intent_id": INTENT_ID,
        "intent_revision": 1,
        "intent_hash": HASH_A,
        "execution_id": EXECUTION_ID,
        "compatibility_execution_mode": mode,
        "goal": "Answer the private user request through the compatibility path.",
        "completion_criteria": [
            {"criterion_id": "C1", "description": "Answer is available.", "required": True}
        ],
    }
    return value


def _context():
    return {
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "context_hash": HASH_B,
        "execution_id": EXECUTION_ID,
        "identity": {"tenant_id": TENANT},
    }


def _snapshot():
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW,
    )


def _plan(mode="GROUNDED_ANSWER", **overrides):
    values = {
        "work_intent": _work_intent(mode),
        "agent_context": _context(),
        "capability_snapshot": _snapshot(),
        "agent_plan_id": PLAN_ID,
    }
    return build_deterministic_agent_plan(**{**values, **overrides})


def _factory(*, with_schema=True, seed=True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_execution_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_work_intent (
                    tenant_id TEXT NOT NULL, work_intent_id TEXT NOT NULL,
                    intent_revision INTEGER NOT NULL, intent_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, work_intent_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_context (
                    tenant_id TEXT NOT NULL, context_id TEXT NOT NULL,
                    context_generation INTEGER NOT NULL, context_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, context_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_capability_snapshot (
                    tenant_id TEXT NOT NULL, capability_snapshot_id TEXT NOT NULL,
                    snapshot_version INTEGER NOT NULL, snapshot_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, capability_snapshot_id),
                    UNIQUE (tenant_id, snapshot_version)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_plan (
                    tenant_id TEXT NOT NULL, agent_plan_id TEXT NOT NULL,
                    agent_plan_version INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL, work_intent_id TEXT NOT NULL,
                    agent_context_id TEXT NOT NULL, capability_snapshot_id TEXT NOT NULL,
                    plan_kind TEXT NOT NULL, plan_hash TEXT NOT NULL,
                    plan_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_plan_id),
                    UNIQUE (tenant_id, agent_execution_id, agent_plan_version)
                )
            """))
            if seed:
                connection.execute(
                    text("INSERT INTO ae_agent_execution VALUES (:t, :e)"),
                    {"t": TENANT, "e": EXECUTION_ID},
                )
                connection.execute(
                    text("INSERT INTO ae_work_intent VALUES (:t, :i, 1, :h)"),
                    {"t": TENANT, "i": INTENT_ID, "h": HASH_A},
                )
                connection.execute(
                    text("INSERT INTO ae_agent_context VALUES (:t, :c, 1, :h)"),
                    {"t": TENANT, "c": CONTEXT_ID, "h": HASH_B},
                )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if with_schema and seed:
        SqlAlchemyCapabilitySnapshotRepository(factory).save(_snapshot())
    return factory


def _rehash(plan):
    plan["plan_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    return plan


@pytest.mark.parametrize(
    ("mode", "kind", "step_count", "report_kind"),
    [
        ("GENERAL_ANSWER", "DIRECT", 1, None),
        ("GROUNDED_ANSWER", "KNOWN_TEMPLATE", 2, "INTERACTIVE_RESPONSE"),
        ("DOCUMENT_SUMMARY", "KNOWN_TEMPLATE", 2, "INTERACTIVE_RESPONSE"),
        ("DOCUMENT_GENERATION", "KNOWN_TEMPLATE", 2, "ARTIFACT"),
    ],
)
def test_builder_emits_contract_valid_deterministic_profiles(
    mode, kind, step_count, report_kind
) -> None:
    first = _plan(mode)
    second = _plan(mode)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first)

    assert first == second
    assert first["plan_kind"] == kind
    assert len(first["steps"]) == step_count
    assert first["planning_constraints"] == {
        "max_plan_steps": 12,
        "max_delegation_depth": 0,
        "max_parallel_steps": 1,
    }
    assert first["steps"][-1]["report"] is None or first["steps"][-1]["report"][
        "report_kind"
    ] == report_kind
    assert first["completion_criteria"][0]["required_terminal_step_refs"] == [
        f"S{step_count}"
    ]


def test_builder_rejects_untrusted_or_incomplete_inputs() -> None:
    bad_context = _context()
    bad_context["execution_id"] = OTHER_PLAN_ID
    with pytest.raises(AgentPlanError, match="does not match"):
        _plan(agent_context=bad_context)

    bad_identity = _context()
    bad_identity["identity"] = "private"
    with pytest.raises(AgentPlanError, match="identity"):
        _plan(agent_context=bad_identity)

    other_tenant = _snapshot()
    other_tenant["tenant_id"] = "other"
    with pytest.raises(AgentPlanError, match="tenant"):
        _plan(capability_snapshot=other_tenant)

    with pytest.raises(AgentPlanError, match="unsupported"):
        _plan("FUTURE_DYNAMIC")

    no_criteria = _work_intent()
    no_criteria["completion_criteria"] = []
    with pytest.raises(AgentPlanError, match="criteria"):
        _plan(work_intent=no_criteria)

    malformed = _work_intent()
    malformed["completion_criteria"] = ["private"]
    with pytest.raises(AgentPlanError, match="malformed"):
        _plan(work_intent=malformed)

    bad_bool = _work_intent()
    bad_bool["completion_criteria"][0]["required"] = "yes"
    with pytest.raises(AgentPlanError, match="boolean"):
        _plan(work_intent=bad_bool)


def test_builder_requires_exact_capability_versions() -> None:
    snapshot = _snapshot()
    snapshot["capabilities"][0]["capability_version"] = "p5.2"
    snapshot["capabilities"].sort(
        key=lambda item: (item["capability_id"], item["capability_version"])
    )
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )
    with pytest.raises(CapabilitySnapshotError) as exc_info:
        _plan(capability_snapshot=snapshot)
    assert exc_info.value.error_code == "ae.capability_exact_version_unavailable"


def test_repository_is_idempotent_exact_lineage_and_restart_safe() -> None:
    factory = _factory()
    repository = SqlAlchemyAgentPlanRepository(factory)
    plan = _plan()

    assert repository.get(tenant_id=TENANT, agent_plan_id=PLAN_ID) is None
    assert repository.save(tenant_id=TENANT, agent_plan=plan, created_at=NOW) == plan
    assert repository.save(tenant_id=TENANT, agent_plan=plan, created_at=NOW) == plan
    assert (
        SqlAlchemyAgentPlanRepository(factory).get(
            tenant_id=TENANT, agent_plan_id=PLAN_ID
        )
        == plan
    )

    changed = _plan()
    changed["goal"] = "Changed immutable goal."
    _rehash(changed)
    with pytest.raises(AgentPlanError) as immutable:
        repository.save(tenant_id=TENANT, agent_plan=changed, created_at=NOW)
    assert immutable.value.error_code == "ae.agent_plan_immutable_conflict"

    conflicting = _plan(agent_plan_id=OTHER_PLAN_ID)
    with pytest.raises(AgentPlanError) as version:
        repository.save(tenant_id=TENANT, agent_plan=conflicting, created_at=NOW)
    assert version.value.error_code == "ae.agent_plan_version_conflict"


def test_repository_requires_exact_lineage_and_contiguous_versions() -> None:
    factory = _factory()
    repository = SqlAlchemyAgentPlanRepository(factory)
    mismatch = _plan()
    mismatch["work_intent_ref"]["hash"] = "sha256:" + "c" * 64
    _rehash(mismatch)
    with pytest.raises(AgentPlanError) as lineage:
        repository.save(tenant_id=TENANT, agent_plan=mismatch, created_at=NOW)
    assert lineage.value.error_code == "ae.agent_plan_lineage_mismatch"

    skipped = _plan(agent_plan_id=OTHER_PLAN_ID, agent_plan_version=2)
    with pytest.raises(AgentPlanError) as chain:
        repository.save(tenant_id=TENANT, agent_plan=skipped, created_at=NOW)
    assert chain.value.error_code == "ae.agent_plan_version_chain_invalid"

    repository.save(tenant_id=TENANT, agent_plan=_plan(), created_at=NOW)
    second = _plan(agent_plan_id=OTHER_PLAN_ID, agent_plan_version=2)
    assert repository.save(tenant_id=TENANT, agent_plan=second, created_at=NOW) == second


@pytest.mark.parametrize(
    "mutator",
    [
        lambda plan: plan.update(schema_version="1.0"),
        lambda plan: plan.update(agent_plan_id="bad"),
        lambda plan: plan.update(agent_plan_version=True),
        lambda plan: plan.update(plan_kind="UNKNOWN"),
        lambda plan: plan.update(goal=""),
        lambda plan: plan.update(completion_criteria=[]),
        lambda plan: plan.update(steps=[]),
        lambda plan: plan.update(planning_constraints={}),
        lambda plan: plan.update(planner_provenance="bad"),
        lambda plan: plan["steps"][0].update(depends_on=["bad"]),
        lambda plan: plan["steps"][0].update(required_capability="bad"),
        lambda plan: plan["steps"][0].update(input_bindings=[{"bad": True}]),
        lambda plan: plan["steps"][0].update(completion_criteria=[]),
        lambda plan: plan["steps"][0].update(aggregation={"mode": "bad", "source_step_refs": ["S1"]}),
        lambda plan: plan["steps"][1].update(report={"report_kind": "bad", "source_step_refs": ["S1"]}),
        lambda plan: plan["planner_provenance"].update(prompt_content_sha256="bad"),
        lambda plan: plan.update(private_prompt="forbidden"),
    ],
)
def test_repository_rejects_malformed_plan_contracts(mutator) -> None:
    plan = _plan()
    mutator(plan)
    _rehash(plan)
    with pytest.raises(AgentPlanError):
        SqlAlchemyAgentPlanRepository(_factory()).save(
            tenant_id=TENANT, agent_plan=plan, created_at=NOW
        )


def test_repository_rejects_hash_tampering_bad_time_and_wraps_store_failures() -> None:
    factory = _factory()
    repository = SqlAlchemyAgentPlanRepository(factory)
    tampered = _plan()
    tampered["goal"] = "tampered"
    with pytest.raises(AgentPlanError, match="hash"):
        repository.save(tenant_id=TENANT, agent_plan=tampered, created_at=NOW)
    with pytest.raises(AgentPlanError, match="timezone"):
        repository.save(
            tenant_id=TENANT, agent_plan=_plan(), created_at="2026-10-13"
        )

    unavailable = SqlAlchemyAgentPlanRepository(_factory(with_schema=False))
    with pytest.raises(AgentPlanError) as save_error:
        unavailable.save(tenant_id=TENANT, agent_plan=_plan(), created_at=NOW)
    assert save_error.value.error_code == "ae.agent_plan_store_unavailable"
    assert save_error.value.retryable is True
    with pytest.raises(AgentPlanError) as get_error:
        unavailable.get(tenant_id=TENANT, agent_plan_id=PLAN_ID)
    assert get_error.value.error_code == "ae.agent_plan_store_unavailable"
    with pytest.raises(AgentPlanError):
        unavailable.get(tenant_id="", agent_plan_id=PLAN_ID)
    assert str(save_error.value) == "AE AgentPlan store is unavailable."


def test_validator_accepts_all_optional_binding_and_provenance_fields() -> None:
    plan = _plan()
    plan["steps"][0]["input_bindings"] = [
        {
            "target_name": "request",
            "source_type": "LITERAL",
            "source_ref": None,
            "json_pointer": None,
            "literal_value": {"safe": True},
        }
    ]
    plan["planner_provenance"].update(
        {
            "prompt_binding_key": "AE.PLANNER",
            "prompt_template_version_id": OTHER_PLAN_ID,
            "prompt_content_sha256": "c" * 64,
            "rendered_prompt_hash": "d" * 64,
            "model_profile": "mock",
            "model_ref": "provider://mock/model",
        }
    )
    _rehash(plan)

    assert module._validate_plan(plan) == plan


@pytest.mark.parametrize(
    "mutator",
    [
        lambda plan: plan["completion_criteria"][0].update(private=True),
        lambda plan: plan["completion_criteria"][0].update(criterion_id="bad"),
        lambda plan: plan["completion_criteria"][0].update(required="yes"),
        lambda plan: plan["completion_criteria"][0].update(
            required_terminal_step_refs=[]
        ),
        lambda plan: plan["steps"][0].update(private=True),
        lambda plan: plan["steps"][0].update(step_id="bad"),
        lambda plan: plan["steps"][0].update(step_type="UNKNOWN"),
        lambda plan: plan["steps"][0].update(depends_on="S1"),
        lambda plan: plan["steps"][0].update(depends_on=["S1", "S1"]),
        lambda plan: plan["steps"][0].update(
            capability_version_constraint="x" * 65
        ),
        lambda plan: plan["steps"][0].update(input_bindings=[{}] * 33),
        lambda plan: plan["steps"][0].update(
            input_bindings=[{"target_name": "Bad", "source_type": "LITERAL"}]
        ),
        lambda plan: plan["steps"][0].update(
            input_bindings=[{"target_name": "ok", "source_type": "BAD"}]
        ),
        lambda plan: plan["steps"][0].update(
            aggregation={"mode": "DETERMINISTIC"}
        ),
        lambda plan: plan["steps"][0].update(
            aggregation={"mode": "DETERMINISTIC", "source_step_refs": []}
        ),
        lambda plan: plan["steps"][1].update(report={"report_kind": "ARTIFACT"}),
        lambda plan: plan["steps"][1].update(
            report={"report_kind": "ARTIFACT", "source_step_refs": []}
        ),
        lambda plan: plan["planner_provenance"].update(builder_type="UNKNOWN"),
        lambda plan: plan["planner_provenance"].update(route_decision_ref=""),
        lambda plan: plan["planner_provenance"].update(template_ref=""),
        lambda plan: plan["planner_provenance"].update(
            prompt_template_version_id="bad"
        ),
        lambda plan: plan["work_intent_ref"].update(private=True),
        lambda plan: plan["work_intent_ref"].update(version=0),
        lambda plan: plan["work_intent_ref"].update(hash="bad"),
        lambda plan: plan.update(agent_plan_id=None),
        lambda plan: plan.update(goal=float("nan")),
    ],
)
def test_internal_validator_fail_closes_every_contract_family(mutator) -> None:
    plan = _plan()
    mutator(plan)
    try:
        _rehash(plan)
    except ValueError:
        pass
    with pytest.raises(AgentPlanError):
        module._validate_plan(plan)


def test_repository_surfaces_unreloadable_write_conflict(monkeypatch) -> None:
    monkeypatch.setattr(module, "_load_plan", lambda *args: None)
    monkeypatch.setattr(module, "_load_plan_by_version", lambda *args: None)

    with pytest.raises(AgentPlanError) as exc_info:
        SqlAlchemyAgentPlanRepository(_factory()).save(
            tenant_id=TENANT, agent_plan=_plan(), created_at=NOW
        )

    assert exc_info.value.error_code == "ae.agent_plan_write_conflict"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("value", [None, "not-a-date"])
def test_repository_rejects_non_rfc3339_created_at(value) -> None:
    with pytest.raises(AgentPlanError):
        SqlAlchemyAgentPlanRepository(_factory()).save(
            tenant_id=TENANT, agent_plan=_plan(), created_at=value
        )
