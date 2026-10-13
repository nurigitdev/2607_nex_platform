from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


ROOT = Path(__file__).resolve().parents[1]
P5 = ROOT / "docs" / "transition" / "P5"
CONTRACTS = P5 / "contracts"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
UUID_1 = "11111111-1111-4111-8111-111111111111"
UUID_2 = "22222222-2222-4222-8222-222222222222"
UUID_3 = "33333333-3333-4333-8333-333333333333"
UUID_4 = "44444444-4444-4444-8444-444444444444"
UUID_5 = "55555555-5555-4555-8555-555555555555"
UUID_6 = "66666666-6666-4666-8666-666666666666"
NOW = "2026-10-13T04:00:00Z"


def _schema(name: str) -> dict[str, object]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    schema = _schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _versioned(ref_id: str, version: int, digest: str) -> dict[str, object]:
    return {"id": ref_id, "version": version, "hash": digest}


def _work_intent() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "work_intent_id": UUID_2,
        "intent_revision": 1,
        "supersedes_work_intent_id": None,
        "execution_id": UUID_1,
        "source": {
            "source_type": "PROMPT",
            "source_ref": f"AE:INTERACTION:{UUID_3}",
            "actor_ref": "OA:SUBJECT:employee-100",
            "received_at": NOW,
        },
        "execution_mode": "INTERACTIVE",
        "compatibility_execution_mode": "GROUNDED_ANSWER",
        "project_ref": None,
        "intent_label": "grounded_question",
        "goal": "Answer the question using authorized evidence.",
        "work_class": "QUERY",
        "required_capability_hints": ["AE.CHAT.COMPATIBILITY"],
        "entity_selectors": [],
        "parameter_candidates": [],
        "constraints": [],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "A grounded response is returned.",
                "required": True,
                "result_contract_ref": "contract://nex/ae/grounded-answer/v1",
            }
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "confidence": {"overall": 1.0, "intent": 1.0, "entities": None, "parameters": None},
        "provenance": {
            "resolver_type": "DETERMINISTIC_POLICY",
            "intent_decision_schema_version": "ae_intent_decision.v1",
            "intent_decision_hash": HASH_A,
            "input_context_hash": HASH_B,
            "prompt_binding_key": None,
            "prompt_template_version_id": None,
            "prompt_content_sha256": None,
            "rendered_prompt_hash": None,
            "model_profile": None,
            "model_ref": None,
        },
        "intent_hash": HASH_C,
    }


def _agent_context() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "context_id": UUID_3,
        "context_generation": 1,
        "execution_id": UUID_1,
        "work_intent_ref": _versioned(UUID_2, 1, HASH_C),
        "identity": {
            "tenant_id": "tenant-a",
            "principal_id": "employee-100",
            "agent_id": UUID_4,
            "agent_type": "IA",
        },
        "interaction": {
            "workspace_id": UUID_5,
            "conversation_id": UUID_6,
            "interaction_id": UUID_3,
        },
        "project_ref": None,
        "authority_ref": "OA:EAC:decision-1",
        "resolved_entities": [],
        "retrieval_refs": [],
        "evidence_refs": [],
        "runtime_policy_ref": {
            "rule_id": "ae.grounded_answer.v1",
            "rule_version": "v1",
            "rule_hash": HASH_A,
        },
        "conflicts": [],
        "degradations": [],
        "context_manifest": [
            {
                "kind": "INTERACTION_REF",
                "source_ref": f"AE:INTERACTION:{UUID_3}",
                "source_version": "1",
                "content_hash": HASH_B,
                "as_of": NOW,
            }
        ],
        "budget": {
            "budget_tokens": 4096,
            "estimated_used_tokens": 128,
            "truncated_optional_items": 0,
        },
        "context_hash": HASH_D,
        "built_at": NOW,
    }


def _capability_snapshot() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "tenant_id": "tenant-a",
        "capability_snapshot_id": UUID_4,
        "snapshot_version": 1,
        "capabilities": [
            {
                "capability_id": "AE.CHAT.COMPATIBILITY",
                "capability_version": "p5.1",
                "status": "ACTIVE",
                "allowed_logical_step_types": ["LOCAL_CAPABILITY"],
                "executable_step_type": "CANONICAL_CAPABILITY",
                "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
                "input_contract_ref": "contract://nex/ae/chat-request/v1",
                "output_contract_ref": "contract://nex/ae/chat-result/v1",
                "operation_semantics": "GENERATE",
            },
            {
                "capability_id": "AE.RESULT.REPORT",
                "capability_version": "p5.1",
                "status": "ACTIVE",
                "allowed_logical_step_types": ["REPORT"],
                "executable_step_type": "REPORT",
                "executor_kind": "DETERMINISTIC_REPORT",
                "input_contract_ref": "contract://nex/ae/step-result/v1",
                "output_contract_ref": "contract://nex/ae/interactive-response/v1",
                "operation_semantics": "REPORT",
            },
        ],
        "snapshot_hash": HASH_A,
        "created_at": NOW,
    }


def _agent_plan() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "agent_plan_id": UUID_5,
        "agent_plan_version": 1,
        "supersedes_agent_plan_id": None,
        "execution_id": UUID_1,
        "work_intent_ref": _versioned(UUID_2, 1, HASH_C),
        "agent_context_ref": _versioned(UUID_3, 1, HASH_D),
        "capability_snapshot_ref": _versioned(UUID_4, 1, HASH_A),
        "plan_kind": "KNOWN_TEMPLATE",
        "goal": "Produce a grounded interactive response.",
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "The response projection is ready.",
                "required": True,
                "required_terminal_step_refs": ["S2"],
            }
        ],
        "planning_constraints": {
            "max_plan_steps": 12,
            "max_delegation_depth": 0,
            "max_parallel_steps": 1,
        },
        "steps": [
            {
                "step_id": "S1",
                "step_type": "LOCAL_CAPABILITY",
                "title": "Run compatibility chat",
                "objective": "Use the existing owner-scoped Chat/RAG path.",
                "depends_on": [],
                "required_capability": "AE.CHAT.COMPATIBILITY",
                "capability_version_constraint": "p5.1",
                "input_bindings": [],
                "output_contract_ref": "contract://nex/ae/chat-result/v1",
                "completion_criteria": ["Compatibility execution is terminal."],
                "aggregation": None,
                "report": None,
            },
            {
                "step_id": "S2",
                "step_type": "REPORT",
                "title": "Project interactive response",
                "objective": "Project the verified compatibility result.",
                "depends_on": ["S1"],
                "required_capability": None,
                "capability_version_constraint": None,
                "input_bindings": [
                    {
                        "target_name": "source_result",
                        "source_type": "STEP_OUTPUT",
                        "source_ref": "S1",
                        "json_pointer": "$",
                    }
                ],
                "output_contract_ref": "contract://nex/ae/interactive-response/v1",
                "completion_criteria": ["A response projection is available."],
                "aggregation": None,
                "report": {
                    "report_kind": "INTERACTIVE_RESPONSE",
                    "source_step_refs": ["S1"],
                },
            },
        ],
        "planner_provenance": {
            "builder_type": "TEMPLATE_BINDER",
            "route_decision_ref": "plan-profile://ae/grounded-answer/p5.1",
            "template_ref": "plan-template://ae/grounded-answer/p5.1",
            "input_context_hash": HASH_D,
            "prompt_binding_key": None,
            "prompt_template_version_id": None,
            "prompt_content_sha256": None,
            "rendered_prompt_hash": None,
            "model_profile": None,
            "model_ref": None,
        },
        "plan_hash": HASH_B,
    }


def _validation_result() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "validation_result_id": UUID_6,
        "agent_plan_ref": _versioned(UUID_5, 1, HASH_B),
        "execution_id": UUID_1,
        "validator_version": "p5-plan-validator/1.0",
        "status": "VALID",
        "validated_context_ref": _versioned(UUID_3, 1, HASH_D),
        "issues": [],
        "topological_step_order": ["S1", "S2"],
        "validated_at": NOW,
        "result_hash": HASH_C,
    }


def _executable_plan() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "executable_plan_id": UUID_6,
        "executable_plan_version": 1,
        "execution_id": UUID_1,
        "agent_plan_ref": _versioned(UUID_5, 1, HASH_B),
        "work_intent_ref": _versioned(UUID_2, 1, HASH_C),
        "agent_context_ref": _versioned(UUID_3, 1, HASH_D),
        "capability_snapshot_ref": _versioned(UUID_4, 1, HASH_A),
        "validation_result_ref": _versioned(UUID_6, 1, HASH_C),
        "compiler_version": "p5-plan-compiler/1.0",
        "policy_snapshot_ref": "AE:RUNTIME_POLICY:ae.grounded_answer.v1",
        "authority_snapshot_ref": "OA:EAC:decision-1",
        "steps": [
            {
                "executable_step_id": "E1",
                "step_index": 0,
                "logical_step_ref": "S1",
                "injected_for_logical_step_ref": None,
                "step_type": "CANONICAL_CAPABILITY",
                "executor_kind": "P4_CHAT_RAG_COMPATIBILITY",
                "title": "Run compatibility chat",
                "depends_on": [],
                "required_capability": "AE.CHAT.COMPATIBILITY",
                "capability_version": "p5.1",
                "compiled_input_bindings": [],
                "output_contract_ref": "contract://nex/ae/chat-result/v1",
                "timeout_policy_ref": "policy://nex/ae/chat-timeout/v1",
                "retry_policy_ref": "policy://nex/ae/chat-retry/v1",
                "step_contract_hash": HASH_A,
            },
            {
                "executable_step_id": "E2",
                "step_index": 1,
                "logical_step_ref": "S2",
                "injected_for_logical_step_ref": None,
                "step_type": "REPORT",
                "executor_kind": "DETERMINISTIC_REPORT",
                "title": "Project interactive response",
                "depends_on": ["E1"],
                "required_capability": "AE.RESULT.REPORT",
                "capability_version": "p5.1",
                "compiled_input_bindings": [
                    {
                        "target_name": "source_result",
                        "binding_type": "EXECUTABLE_STEP_OUTPUT",
                        "source_ref": "E1:$",
                        "binding_hash": HASH_B,
                    }
                ],
                "output_contract_ref": "contract://nex/ae/interactive-response/v1",
                "timeout_policy_ref": None,
                "retry_policy_ref": None,
                "step_contract_hash": HASH_C,
            },
        ],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "required": True,
                "required_terminal_step_refs": ["E2"],
            }
        ],
        "logical_step_mapping": [
            {"logical_step_id": "S1", "executable_step_ids": ["E1"]},
            {"logical_step_id": "S2", "executable_step_ids": ["E2"]},
        ],
        "runtime_constraints": {"max_parallel_steps": 1, "max_steps_per_run_slice": 1},
        "compiled_at": NOW,
        "executable_plan_hash": HASH_D,
    }


@pytest.mark.parametrize(
    ("schema_name", "factory"),
    [
        ("p5-work-intent-v1.schema.json", _work_intent),
        ("p5-agent-context-v1.schema.json", _agent_context),
        ("p5-capability-snapshot-v1.schema.json", _capability_snapshot),
        ("p5-agent-plan-v1.schema.json", _agent_plan),
        ("p5-plan-validation-result-v1.schema.json", _validation_result),
        ("p5-executable-plan-v1.schema.json", _executable_plan),
    ],
)
def test_ca01_transition_contract_examples_validate(schema_name, factory):
    _validator(schema_name).validate(factory())


def test_ca01_step_result_contract_accepts_terminal_result_only():
    result = {
        "schema_version": "1.0",
        "step_result_id": UUID_1,
        "execution_id": UUID_2,
        "executable_plan_id": UUID_3,
        "executable_step_id": "E1",
        "logical_step_ref": "S1",
        "attempt_no": 1,
        "status": "SUCCEEDED",
        "result_contract_ref": "contract://nex/ae/chat-result/v1",
        "result_payload": {"result_ref": "AE:CHAT:result-1"},
        "external_refs": [],
        "artifact_refs": [],
        "evidence_refs": [],
        "error_ref": None,
        "business_operation_id": None,
        "operation_fingerprint": None,
        "started_at": NOW,
        "completed_at": NOW,
        "result_hash": HASH_A,
    }
    validator = _validator("p5-step-result-v1.schema.json")
    validator.validate(result)
    result["status"] = "WAITING"
    with pytest.raises(ValidationError):
        validator.validate(result)


def test_ca01_work_intent_accepts_project_neutral_prompt_and_rejects_event():
    validator = _validator("p5-work-intent-v1.schema.json")
    intent = _work_intent()
    validator.validate(intent)
    invalid = deepcopy(intent)
    invalid["source"]["source_type"] = "EVENT"
    with pytest.raises(ValidationError):
        validator.validate(invalid)


def test_ca01_plan_rejects_legacy_plan_kind_and_more_than_twelve_steps():
    validator = _validator("p5-agent-plan-v1.schema.json")
    plan = _agent_plan()
    legacy = deepcopy(plan)
    legacy["plan_kind"] = "ONE_STEP"
    with pytest.raises(ValidationError):
        validator.validate(legacy)

    oversized = deepcopy(plan)
    oversized["steps"] = [
        {
            **deepcopy(plan["steps"][0]),
            "step_id": f"S{index}",
            "depends_on": [] if index == 1 else [f"S{index - 1}"],
        }
        for index in range(1, 14)
    ]
    with pytest.raises(ValidationError):
        validator.validate(oversized)


def test_ca01_document_set_includes_prompt_governance_and_slice_ownership():
    readme = (P5 / "README.md").read_text(encoding="utf-8")
    prompt_design = (
        P5 / "P5_LLM_Prompt_Template_Registry_and_Governance_Design_v1.0.md"
    ).read_text(encoding="utf-8")
    implementation = (
        P5 / "P5_Source_Audit_and_Implementation_Plan_v1.0.md"
    ).read_text(encoding="utf-8")
    issues = (P5 / "P5_Issue_Register_v1.0.md").read_text(encoding="utf-8")

    assert "P5_LLM_Prompt_Template_Registry_and_Governance_Design_v1.0.md" in readme
    assert "P5_LLM_Prompt_Registry_Traceability_v1.0.md" in readme
    assert "every LLM-dependent stage enabled" in prompt_design
    assert "Prompt Registry Hardening" in implementation
    assert "P5-ISSUE-017" in issues and "CLOSED_DESIGN" in issues


def test_ca01_documents_use_frozen_validation_and_local_skill_boundaries():
    readme = (P5 / "README.md").read_text(encoding="utf-8")
    architecture = (P5 / "P5_Architecture_Decisions_v1.0.md").read_text(
        encoding="utf-8"
    )
    srs = (
        P5 / "P5_Agent_Planning_and_Execution_Foundation_SRS_v1.0.md"
    ).read_text(encoding="utf-8")
    traceability = (
        P5 / "P5_Intent_Context_Plan_Compiler_Traceability_v1.0.md"
    ).read_text(encoding="utf-8")

    assert "validation status=VALID" in readme
    assert "compile-ready but non-runnable" not in architecture
    assert "before an\nExecutablePlan or READY step is materialized" in architecture
    assert "contracts/p5-plan-validation-result-v1.schema.json" in srs
    assert "lossy `PASS/FAIL` field" in srs
    assert "Validation PASS/FAIL" not in traceability


def test_ca01_frozen_source_manifest_hashes_match_read_only_inputs():
    manifest = P5 / "P5_CA01_Frozen_Source_Manifest_v1.0.csv"
    with manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 11
    for row in rows:
        source = ROOT / row["source_path"]
        assert source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row["sha256"]
