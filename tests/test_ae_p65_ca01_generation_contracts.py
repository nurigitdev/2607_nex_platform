from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.agent_execution import AGENT_RUNTIME_MODES
from nex_ae_api.work_intent import PLANNING_MODES


ROOT = Path(__file__).resolve().parents[1]
P65 = ROOT / "docs" / "transition" / "P6_5"
CONTRACTS = P65 / "contracts"
EXAMPLES = CONTRACTS / "examples"
NEGATIVE = CONTRACTS / "tests" / "negative"
MO_GENERATION_REQUEST = (
    ROOT
    / "contracts"
    / "schemas"
    / "service"
    / "nex_mo"
    / "generation_request.v1.schema.json"
)

PAIRS = (
    ("p65-intent-candidate-v1.schema.json", "p65-intent-candidate-v1.json"),
    (
        "p65-context-candidate-set-v1.schema.json",
        "p65-context-candidate-set-v1.json",
    ),
    ("p65-plan-candidate-v1.schema.json", "p65-plan-candidate-v1.json"),
    (
        "p65-semantic-candidate-evidence-v1.schema.json",
        "p65-semantic-candidate-evidence-v1.json",
    ),
)

NEGATIVE_PAIRS = (
    (
        "p65-intent-candidate-v1.schema.json",
        "p65-intent-candidate.authority-field.json",
    ),
    (
        "p65-context-candidate-set-v1.schema.json",
        "p65-context-candidate.permission-field.json",
    ),
    (
        "p65-plan-candidate-v1.schema.json",
        "p65-plan-candidate.delegate-work.json",
    ),
    (
        "p65-semantic-candidate-evidence-v1.schema.json",
        "p65-semantic-candidate-evidence.secret-field.json",
    ),
)

PLATFORM_ENVELOPE_FIELDS = {
    "tenant_id",
    "owner_subject_id",
    "candidate_id",
    "execution_id",
    "candidate_revision",
    "candidate_hash",
    "candidate_payload_storage_ref",
    "prompt_binding_key",
    "prompt_template_version_id",
    "model_profile",
    "model_ref",
    "mo_generation_id",
    "validation_outcome",
}

AUTHORITY_FIELDS = {
    "tenant_authority",
    "principal_authority",
    "role_bindings",
    "permission",
    "permission_grants",
    "project_authority",
    "data_classification_authority",
    "approval_authority",
    "exact_capability_version",
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load(CONTRACTS / schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize(("schema_name", "example_name"), PAIRS)
def test_p65_transition_schemas_and_golden_examples_validate(
    schema_name: str, example_name: str
) -> None:
    _validator(schema_name).validate(_load(EXAMPLES / example_name))


@pytest.mark.parametrize(("schema_name", "fixture_name"), NEGATIVE_PAIRS)
def test_p65_negative_authority_delegation_and_secret_fixtures_fail_closed(
    schema_name: str, fixture_name: str
) -> None:
    with pytest.raises(ValidationError):
        _validator(schema_name).validate(_load(NEGATIVE / fixture_name))


def test_model_payload_schemas_exclude_platform_identity_and_authority() -> None:
    for schema_name in (
        "p65-intent-candidate-v1.schema.json",
        "p65-context-candidate-set-v1.schema.json",
        "p65-plan-candidate-v1.schema.json",
    ):
        schema = _load(CONTRACTS / schema_name)
        assert schema["additionalProperties"] is False
        fields = set(schema["properties"])
        assert fields.isdisjoint(PLATFORM_ENVELOPE_FIELDS)
        assert fields.isdisjoint(AUTHORITY_FIELDS)


def test_intent_candidate_uses_only_existing_compatibility_modes() -> None:
    schema = _load(CONTRACTS / "p65-intent-candidate-v1.schema.json")

    assert set(schema["properties"]["suggested_execution_mode"]["enum"]) == {
        "GENERAL_ANSWER",
        "GROUNDED_ANSWER",
        "DOCUMENT_SUMMARY",
        "DOCUMENT_GENERATION",
    }
    assert schema["properties"]["entity_selectors"]["maxItems"] == 32
    assert schema["properties"]["parameter_candidates"]["maxItems"] == 32


def test_plan_candidate_vocabulary_and_bounds_preserve_p65_scope() -> None:
    schema = _load(CONTRACTS / "p65-plan-candidate-v1.schema.json")
    steps = schema["properties"]["logical_steps"]
    step_type = schema["$defs"]["logicalStep"]["properties"]["step_type"]

    assert steps["maxItems"] == 12
    assert set(step_type["enum"]) == {
        "LOCAL_CAPABILITY",
        "AGGREGATE",
        "REPORT",
    }
    assert "DELEGATE_WORK" not in step_type["enum"]
    assert "LOCAL_SKILL" not in step_type["enum"]


def test_evidence_example_uses_shared_hash_and_content_addressed_reference() -> None:
    candidate_path = EXAMPLES / "p65-intent-candidate-v1.json"
    candidate = _load(candidate_path)
    evidence = _load(EXAMPLES / "p65-semantic-candidate-evidence-v1.json")
    expected_hash = semantic_sha256_hash_ref(candidate)
    digest = expected_hash.removeprefix("sha256:")

    assert evidence["candidate_hash"] == expected_hash
    assert evidence["candidate_payload_size_bytes"] == candidate_path.stat().st_size
    assert evidence["candidate_payload_storage_ref"] == (
        f"ae://semantic-candidates/{evidence['candidate_id']}/{digest}.json"
    )
    assert "provider_endpoint" not in evidence
    assert "api_key" not in evidence
    assert "raw_prompt" not in evidence
    assert "hidden_reasoning" not in evidence


def test_admitted_evidence_requires_payload_hash_reference_and_size() -> None:
    validator = _validator("p65-semantic-candidate-evidence-v1.schema.json")
    evidence = _load(EXAMPLES / "p65-semantic-candidate-evidence-v1.json")
    for field in (
        "candidate_hash",
        "candidate_payload_storage_ref",
        "candidate_payload_size_bytes",
    ):
        invalid = copy.deepcopy(evidence)
        invalid[field] = None
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_existing_rollout_modes_are_reused_without_a_p65_mode_fork() -> None:
    assert PLANNING_MODES == {"disabled", "shadow", "required"}
    assert AGENT_RUNTIME_MODES == {"disabled", "shadow", "required"}


def test_existing_mo_contract_admits_the_closed_p65_wire_shape() -> None:
    schema = _load(MO_GENERATION_REQUEST)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    request = {
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "messages": [
            {"role": "system", "content": "Return one JSON object."},
            {"role": "user", "content": "Untrusted user input."},
        ],
        "response_format": {"type": "json_object"},
        "reasoning_mode": "disabled",
        "max_output_tokens": 768,
        "temperature": 0.0,
        "stream": False,
    }

    validator.validate(request)
    for private_field in ("provider_url", "provider_endpoint", "model_path", "api_key"):
        invalid = {**request, private_field: "forbidden"}
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_ae_source_has_no_direct_vendor_provider_configuration() -> None:
    source_root = ROOT / "services" / "nex-ae-api" / "nex_ae_api"
    forbidden = ("NEX_MO_VLLM_", "NEX_MO_REMOTE_", "execute_remote_generation_request")

    for path in source_root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} directly references {token}"


def test_ca01_closure_freezes_all_eight_decisions_and_exact_bindings() -> None:
    closure = (
        P65 / "P6_5_CA01_Source_Backed_Generation_Contract_Closure_v1.0.md"
    ).read_text(encoding="utf-8")

    for decision in range(1, 9):
        assert f"Decision {decision}" in closure
    for binding in (
        "ae.intent_resolution.default",
        "ae.context_candidate_extraction.default",
        "ae.plan_builder.default",
    ):
        assert binding in closure
    assert "reasoning_mode = disabled" in closure
    assert "ae_semantic_candidate" in closure
    assert "P6.5-CA01 is closed" in closure
    assert "P6.5-S1 is authorized" in closure
