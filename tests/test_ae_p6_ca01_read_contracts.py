from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


ROOT = Path(__file__).resolve().parents[1]
P6 = ROOT / "docs" / "transition" / "P6"
CONTRACTS = P6 / "contracts"
EXAMPLES = CONTRACTS / "examples"

PAIRS = (
    ("p6-context-projection-v1.schema.json", "p6-golden-context-projection-v1.json"),
    (
        "p6-verified-skill-artifact-v1.schema.json",
        "p6-golden-verified-artifact-v1.json",
    ),
    (
        "p6-skill-execution-request-v1.schema.json",
        "p6-golden-skill-execution-request-v1.json",
    ),
    (
        "p6-nsl-result-summary-v1.schema.json",
        "p6-golden-nsl-result-summary-v1.json",
    ),
    (
        "p6-nsl-step-execution-binding-v1.schema.json",
        "p6-golden-step-execution-binding-v1.json",
    ),
    ("p6-step-result-v1.2.schema.json", "p6-golden-step-result-v1.2.json"),
)

EXPECTED_V01_STATUSES = {
    "CREATED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "TOOL_ERROR",
    "VALIDATION_ERROR",
    "LIMIT_EXCEEDED",
    "CANCELLED",
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load(CONTRACTS / schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _example(name: str) -> dict[str, object]:
    return _load(EXAMPLES / name)


def _without(value: dict[str, object], *keys: str) -> dict[str, object]:
    projection = copy.deepcopy(value)
    for key in keys:
        projection.pop(key)
    return projection


@pytest.mark.parametrize(("schema_name", "example_name"), PAIRS)
def test_transition_schemas_and_golden_examples_validate(
    schema_name: str, example_name: str
) -> None:
    _validator(schema_name).validate(_example(example_name))


def test_golden_hashes_use_the_shared_canonical_hash_contract() -> None:
    context = _example("p6-golden-context-projection-v1.json")
    artifact = _example("p6-golden-verified-artifact-v1.json")
    request = _example("p6-golden-skill-execution-request-v1.json")
    summary = _example("p6-golden-nsl-result-summary-v1.json")
    binding = _example("p6-golden-step-execution-binding-v1.json")
    step_result = _example("p6-golden-step-result-v1.2.json")

    trust = copy.deepcopy(artifact["trust_evidence"])
    assert isinstance(trust, dict)
    trust_hash = trust.pop("evidence_hash")
    assert trust_hash == semantic_sha256_hash_ref(trust)
    admission = {
        "decision": "ADMITTED",
        "package_id": artifact["package_id"],
        "package_hash": artifact["package_hash"],
        "publisher_id": artifact["publisher_id"],
        "signing_key_id": artifact["signing_key_id"],
        "governance_status": "ACTIVE",
        "trust_policy_id": artifact["trust_evidence"]["trust_policy_id"],
        "package_trust_evidence_ref": artifact["trust_evidence"]["evidence_ref"],
        "reason_codes": [],
        "decided_at": "2026-10-14T07:00:00Z",
    }
    assert artifact["artifact_admission_decision_hash"] == (
        semantic_sha256_hash_ref(admission)
    )
    assert context["projection_hash"] == semantic_sha256_hash_ref(
        _without(context, "projection_hash")
    )
    assert artifact["artifact_hash"] == semantic_sha256_hash_ref(
        _without(artifact, "artifact_hash")
    )
    assert binding["request_hash"] == semantic_sha256_hash_ref(request)
    assert binding["result_summary_hash"] == semantic_sha256_hash_ref(summary)
    assert step_result["result_hash"] == semantic_sha256_hash_ref(
        _without(
            step_result,
            "step_result_id",
            "started_at",
            "completed_at",
            "result_hash",
        )
    )


def test_golden_lineage_keeps_all_platform_and_nsl_identities_distinct() -> None:
    request = _example("p6-golden-skill-execution-request-v1.json")
    binding = _example("p6-golden-step-execution-binding-v1.json")
    summary = _example("p6-golden-nsl-result-summary-v1.json")
    step_result = _example("p6-golden-step-result-v1.2.json")
    artifact = _example("p6-golden-verified-artifact-v1.json")

    identity_fields = (
        "agent_execution_id",
        "executable_plan_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
    )
    assert len({request[field] for field in identity_fields}) == len(identity_fields)
    for field in identity_fields:
        assert binding[field] == request[field]
    assert summary["nsl_execution_id"] == request["nsl_execution_id"]
    assert summary["business_operation_id"] == request["business_operation_id"]
    assert step_result["business_operation_id"] == request["business_operation_id"]
    assert step_result["execution_id"] == request["agent_execution_id"]
    assert step_result["executable_plan_id"] == request["executable_plan_id"]
    assert step_result["executable_step_id"] == request["executable_step_id"]
    assert binding["verified_artifact_hash"] == artifact["artifact_hash"]


def test_request_input_provenance_and_context_projection_are_bounded() -> None:
    request = _example("p6-golden-skill-execution-request-v1.json")
    context = _example("p6-golden-context-projection-v1.json")

    assert set(request["compiled_inputs"]) == set(request["input_provenance"])
    assert request["context_projection_hash"] == context["projection_hash"]
    assert request["agent_context_hash"] == context["agent_context_hash"]
    assert request["tenant_id"] == context["verified_principal"]["tenant_id"]
    assert "agent_context" not in request
    assert len(context["runtime_context_entries"]) <= 64


def test_result_schema_enumerates_exact_v01_statuses() -> None:
    schema = _load(CONTRACTS / "p6-nsl-result-summary-v1.schema.json")

    assert set(schema["properties"]["execution_status"]["enum"]) == (
        EXPECTED_V01_STATUSES
    )


def test_step_result_v12_enforces_local_skill_business_operation_identity() -> None:
    validator = _validator("p6-step-result-v1.2.schema.json")
    local = _example("p6-golden-step-result-v1.2.json")
    validator.validate(local)

    missing = copy.deepcopy(local)
    missing["business_operation_id"] = None
    with pytest.raises(ValidationError):
        validator.validate(missing)

    non_nsl = copy.deepcopy(local)
    non_nsl["executor_kind"] = "DETERMINISTIC_REPORT"
    with pytest.raises(ValidationError):
        validator.validate(non_nsl)

    non_nsl["business_operation_id"] = None
    validator.validate(non_nsl)


def test_historical_step_result_v11_remains_separately_readable() -> None:
    validator = _validator("p6-step-result-v1.2.schema.json")
    p5_schema = _load(
        ROOT / "docs" / "transition" / "P5" / "contracts" / "p5-step-result-v1.1.schema.json"
    )
    p5_validator = Draft202012Validator(p5_schema, format_checker=FormatChecker())
    current = _example("p6-golden-step-result-v1.2.json")
    historical = copy.deepcopy(current)
    historical["schema_version"] = "1.1"
    historical.pop("executor_kind")
    historical["business_operation_id"] = None

    p5_validator.validate(historical)
    with pytest.raises(ValidationError):
        validator.validate(historical)


def test_result_and_binding_terminal_conditions_fail_closed() -> None:
    result_validator = _validator("p6-nsl-result-summary-v1.schema.json")
    binding_validator = _validator("p6-nsl-step-execution-binding-v1.schema.json")
    result = _example("p6-golden-nsl-result-summary-v1.json")
    binding = _example("p6-golden-step-execution-binding-v1.json")

    no_result = copy.deepcopy(result)
    no_result["result_ref"] = None
    with pytest.raises(ValidationError):
        result_validator.validate(no_result)

    failed_without_error = copy.deepcopy(result)
    failed_without_error.update(
        execution_status="TOOL_ERROR", result_ref=None, result_hash=None
    )
    with pytest.raises(ValidationError):
        result_validator.validate(failed_without_error)

    nonterminal = copy.deepcopy(binding)
    nonterminal["state"] = "RUNNING"
    with pytest.raises(ValidationError):
        binding_validator.validate(nonterminal)

    terminal_without_time = copy.deepcopy(binding)
    terminal_without_time["completed_at"] = None
    with pytest.raises(ValidationError):
        binding_validator.validate(terminal_without_time)


def test_unknown_fields_full_context_and_invalid_trust_are_rejected() -> None:
    request_validator = _validator("p6-skill-execution-request-v1.schema.json")
    context_validator = _validator("p6-context-projection-v1.schema.json")
    artifact_validator = _validator("p6-verified-skill-artifact-v1.schema.json")

    request = _example("p6-golden-skill-execution-request-v1.json")
    request["agent_context"] = {"raw": "forbidden"}
    with pytest.raises(ValidationError):
        request_validator.validate(request)

    context = _example("p6-golden-context-projection-v1.json")
    context["verified_principal"]["verification"] = "UNVERIFIED"
    with pytest.raises(ValidationError):
        context_validator.validate(context)

    artifact = _example("p6-golden-verified-artifact-v1.json")
    artifact["trust_evidence"]["trust_status"] = "INVALID"
    with pytest.raises(ValidationError):
        artifact_validator.validate(artifact)


def test_golden_fixture_records_exact_source_and_isolated_acceptance() -> None:
    fixture = _example("p6-golden-read-fixture-v1.json")

    assert fixture["source"]["commit"] == (
        "803f22aadc3946a48b05472c80b60fe11d9d9554"
    )
    assert fixture["signed_package"]["package_hash"] == (
        "sha256:9e538ec352bddc4ba4a43ac1510759c02491f74f52c50bf4f817f94c9925622e"
    )
    assert fixture["expected"]["isolation_status"] == "COMPLETED"
    assert fixture["expected"]["runtime_status"] == "COMPLETED"
    assert fixture["evidence_profile"]["worker_evidence_policy"] == (
        "SNAPSHOT_REQUIRED"
    )


def test_closure_document_has_no_unmapped_v01_status_or_open_ca01_gate() -> None:
    closure = (
        P6 / "P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md"
    ).read_text(encoding="utf-8")

    for status in EXPECTED_V01_STATUSES:
        assert f"`{status}`" in closure
    assert "P6-CA01 is closed" in closure
    assert "P6-S0" in closure
