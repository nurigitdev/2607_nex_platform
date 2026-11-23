from __future__ import annotations

from copy import deepcopy

import pytest

from nex_runtime.semantic_handoff import SEMANTIC_HANDOFF_SCHEMA_VERSION
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_wc.coordination import _planning_source
from nex_wc.work_items import WorkItemError, validate_delegation_spec


def _handoff() -> dict:
    return {
        "schema_version": SEMANTIC_HANDOFF_SCHEMA_VERSION,
        "tenant_id": "VO00",
        "owner_subject_id": "employee-1001",
        "parent_execution_id": "11111111-1111-4111-8111-111111111111",
        "parent_agent_type": "IA",
        "parent_work_intent_id": "22222222-2222-4222-8222-222222222222",
        "parent_work_intent_hash": "sha256:" + "1" * 64,
        "parent_intent_revision": 1,
        "intent_candidate_id": "33333333-3333-4333-8333-333333333333",
        "intent_candidate_hash": "sha256:" + "2" * 64,
        "intent_evidence_hash": "sha256:" + "3" * 64,
        "context_candidate_id": "44444444-4444-4444-8444-444444444444",
        "context_candidate_hash": "sha256:" + "4" * 64,
        "context_evidence_hash": "sha256:" + "5" * 64,
        "source_type": "PROMPT",
        "source_ref": "AE:INTERACTION:55555555-5555-4555-8555-555555555555",
        "source_interaction_id": "55555555-5555-4555-8555-555555555555",
        "source_revision": 1,
        "created_at": "2026-11-23T09:00:00Z",
        "handoff_hash": "sha256:" + "6" * 64,
    }


def _spec() -> dict:
    handoff = _handoff()
    handoff["handoff_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in handoff.items() if key != "handoff_hash"}
    )
    return {
        "schema_version": "1.3",
        "delegation_id": "66666666-6666-4666-8666-666666666666",
        "tenant_id": "VO00",
        "parent_agent_execution_id": handoff["parent_execution_id"],
        "parent_executable_plan_id": "77777777-7777-4777-8777-777777777777",
        "parent_executable_step_id": "88888888-8888-4888-8888-888888888888",
        "delegation_revision": 1,
        "goal": "Summarize admitted Project evidence.",
        "work_class": "ANALYSIS",
        "required_agent_type": "PA",
        "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
        "project_ref": {"entity_type": "PROJECT", "entity_id": "VO00D260101"},
        "project_scope_ref": "VO00D260101",
        "result_contract_ref": "contract://nex/mybee/project-analysis-result/v1",
        "completion_policy": "OWNER_SUBMITS",
        "correlation_id": "99999999-9999-4999-8999-999999999999",
        "causation_id": None,
        "semantic_handoff": handoff,
    }


def test_wc_v13_delegation_transports_semantic_handoff_to_planning_source():
    spec = validate_delegation_spec(_spec())
    work_item = {
        "work_item_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "goal": spec["goal"],
        "work_class": spec["work_class"],
        "routing_target": {"required_capability": spec["required_capability"]},
        "project_ref": spec["project_ref"],
        "artifact_refs": [],
        "completion_policy": spec["completion_policy"],
        "accountable_owner": {"entity_id": "employee-1001"},
    }

    source = _planning_source(work_item, spec)

    assert source["schema_version"] == "p7.claimed_work_planning_source.v3"
    assert source["semantic_handoff"] == spec["semantic_handoff"]
    assert source["delegation_identity"] == {
        "delegation_id": spec["delegation_id"],
        "delegation_revision": 1,
        "requester_ref": "employee-1001",
        "parent_agent_execution_id": spec["parent_agent_execution_id"],
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("tenant_id", "OTHER", "lineage"),
        (
            "parent_execution_id",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "lineage",
        ),
    ),
)
def test_wc_v13_delegation_rejects_cross_scope_handoff(field, value, message):
    spec = _spec()
    handoff = deepcopy(spec["semantic_handoff"])
    handoff[field] = value
    handoff["handoff_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in handoff.items() if key != "handoff_hash"}
    )
    spec["semantic_handoff"] = handoff

    with pytest.raises(WorkItemError, match=message):
        validate_delegation_spec(spec)


def test_wc_legacy_versions_cannot_smuggle_semantic_handoff():
    for version in ("1.0", "1.1", "1.2"):
        spec = _spec()
        spec["schema_version"] = version
        with pytest.raises(WorkItemError):
            validate_delegation_spec(spec)
