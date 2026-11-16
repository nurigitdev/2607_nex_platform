from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from nex_ae_api import work_intent as work_intent_module
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc import coordination as coordination_module
from nex_wc.work_items import WorkItemError, validate_delegation_spec
from referencing import Registry, Resource

# Successor AE/WC contracts are admitted before activation in 01B.2/01B.3.
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "contracts" / "schemas" / "service"
EXAMPLE_ROOT = ROOT / "contracts" / "examples" / "service"
BOUNDARY = (
    ROOT / "domains" / "mybee" / "config"
    / "m1_transaction_orchestration_boundary.v1.json"
)

CONTEXT_SCHEMA = SCHEMA_ROOT / "nex_ae_api" / "business_request_context.v1.schema.json"
WORK_INTENT_SCHEMA = SCHEMA_ROOT / "nex_ae_api" / "work_intent.v1_2.schema.json"
DELEGATION_SCHEMA = SCHEMA_ROOT / "nex_wc" / "delegation_spec.v1_2.schema.json"
PLANNING_SOURCE_SCHEMA = (
    SCHEMA_ROOT / "nex_wc" / "claimed_work_planning_source.v2.schema.json"
)

CONTEXT_EXAMPLE = EXAMPLE_ROOT / "ae_business_request_context.finance_voucher.json"
WORK_INTENT_EXAMPLE = EXAMPLE_ROOT / "ae_work_intent.business_transaction.v1_2.json"
DELEGATION_EXAMPLE = EXAMPLE_ROOT / "wc_delegation_spec.business_context.v1_2.json"
PLANNING_SOURCE_EXAMPLE = (
    EXAMPLE_ROOT / "wc_claimed_work_planning_source.business_context.v2.json"
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for path in (
        CONTEXT_SCHEMA,
        WORK_INTENT_SCHEMA,
        DELEGATION_SCHEMA,
        PLANNING_SOURCE_SCHEMA,
    ):
        contents = _json(path)
        registry = registry.with_resource(
            str(contents["$id"]), Resource.from_contents(contents)
        )
    return registry


def _validator(path: Path) -> Draft202012Validator:
    schema = _json(path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=_registry(),
        format_checker=FormatChecker(),
    )


@pytest.mark.parametrize(
    ("schema_path", "example_path"),
    (
        (CONTEXT_SCHEMA, CONTEXT_EXAMPLE),
        (WORK_INTENT_SCHEMA, WORK_INTENT_EXAMPLE),
        (DELEGATION_SCHEMA, DELEGATION_EXAMPLE),
        (PLANNING_SOURCE_SCHEMA, PLANNING_SOURCE_EXAMPLE),
    ),
)
def test_01b1_positive_contract_examples_validate(
    schema_path: Path, example_path: Path
) -> None:
    _validator(schema_path).validate(_json(example_path))


def test_01b1_context_is_semantically_hash_bound_at_every_frozen_boundary() -> None:
    context = _json(CONTEXT_EXAMPLE)
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in context.items() if key != "context_hash"}
    )
    assert context["context_hash"] == expected

    envelopes = (
        _json(WORK_INTENT_EXAMPLE),
        _json(DELEGATION_EXAMPLE),
        _json(PLANNING_SOURCE_EXAMPLE),
    )
    for envelope in envelopes:
        assert envelope["business_request_context"] == context
        assert envelope["business_context_hash"] == expected

    work_intent = envelopes[0]
    assert work_intent["intent_hash"] == semantic_sha256_hash_ref(
        {
            key: value
            for key, value in work_intent.items()
            if key != "intent_hash"
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("raw_prompt", "private prompt must not be duplicated"),
        ("accounting_approval_evidence_id", "model-supplied-proof"),
        ("candidate_id", "model-supplied-candidate"),
        ("fx_rate", "1350.20"),
        ("period_status", "OPEN"),
    ),
)
def test_01b1_business_context_rejects_prompt_and_authority_fields(
    field: str, value: str
) -> None:
    invalid = _json(CONTEXT_EXAMPLE)
    invalid[field] = value
    with pytest.raises(ValidationError):
        _validator(CONTEXT_SCHEMA).validate(invalid)


def test_01b1_wrappers_require_context_and_exact_successor_versions() -> None:
    cases = (
        (WORK_INTENT_SCHEMA, WORK_INTENT_EXAMPLE, "business_request_context"),
        (DELEGATION_SCHEMA, DELEGATION_EXAMPLE, "business_context_hash"),
        (PLANNING_SOURCE_SCHEMA, PLANNING_SOURCE_EXAMPLE, "delegation_identity"),
    )
    for schema_path, example_path, missing_field in cases:
        invalid = _json(example_path)
        invalid.pop(missing_field)
        with pytest.raises(ValidationError):
            _validator(schema_path).validate(invalid)

    legacy = _json(PLANNING_SOURCE_EXAMPLE)
    legacy["schema_version"] = "p7.claimed_work_planning_source.v1"
    with pytest.raises(ValidationError):
        _validator(PLANNING_SOURCE_SCHEMA).validate(legacy)


def test_01b1_context_mutation_changes_hash_and_cannot_reuse_wrapper_binding() -> None:
    context = _json(CONTEXT_EXAMPLE)
    changed = copy.deepcopy(context)
    changed["transaction"]["amount"] = "2451.00"
    changed_hash = semantic_sha256_hash_ref(
        {key: value for key, value in changed.items() if key != "context_hash"}
    )
    assert changed_hash != context["context_hash"]

    wrapper = _json(DELEGATION_EXAMPLE)
    wrapper["business_request_context"] = changed
    assert wrapper["business_context_hash"] != changed_hash


def test_01b1_boundary_manifest_freezes_sources_operations_and_shortcuts() -> None:
    boundary = _json(BOUNDARY)
    assert boundary["status"] == "CONTRACT_ADMITTED_RUNTIME_UNCHANGED"
    assert boundary["database_migration"] is False
    assert boundary["remote_provider_required"] is False
    assert boundary["next_slice"] == "CP-M1-E2E-FX-01B.2"
    assert {
        item["operation_id"] for item in boundary["operation_activation"]
    } == {
        "PROJECT.WORK_CODE_SET.GET",
        "FINANCE.VOUCHER_CANDIDATE.CREATE_V2",
        "FINANCE.VOUCHER_CANDIDATE.VALIDATE",
        "FINANCE.VOUCHER_POSTING.ADMIT",
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "FINANCE.COST_ALLOCATION.RUN",
        "FINANCE.COST_ALLOCATION.VERIFY",
        "FINANCE.PROJECT_PNL.GET",
    }
    assert set(boundary["prohibited_shortcuts"]) == {
        "RAW_PROMPT_DUPLICATION",
        "MODEL_SUPPLIED_AUTHORITY",
        "FIXED_BUSINESS_RUNTIME_VALUE",
        "GOLDEN_A_FALLBACK",
        "RUNNER_DIRECT_PRIVATE_SQL",
        "RUNNER_OWNED_PRODUCT_TRANSITION",
        "UNSIGNED_SKILL_SUBSTITUTION",
    }
    for source in boundary["source_boundaries"]:
        assert (ROOT / source["path"]).is_file()


def test_01b1_successor_contracts_are_admitted_but_runtime_is_not_activated() -> None:
    assert work_intent_module.WORK_INTENT_SCHEMA_VERSION == "1.1"

    with pytest.raises(WorkItemError):
        validate_delegation_spec(_json(DELEGATION_EXAMPLE))

    with pytest.raises(work_intent_module.WorkIntentError):
        work_intent_module._claimed_planning_source(_json(PLANNING_SOURCE_EXAMPLE))

    assert '"schema_version": "p7.claimed_work_planning_source.v1"' in inspect.getsource(
        coordination_module._planning_source
    )


def test_01b1_contract_inventory_registers_the_successor_examples() -> None:
    inventory = _json(ROOT / "contracts" / "examples" / "index.json")["examples"]
    registered = {(item["path"], item["schema"]) for item in inventory}
    assert registered >= {
        (
            "examples/service/ae_business_request_context.finance_voucher.json",
            "schemas/service/nex_ae_api/business_request_context.v1.schema.json",
        ),
        (
            "examples/service/ae_work_intent.business_transaction.v1_2.json",
            "schemas/service/nex_ae_api/work_intent.v1_2.schema.json",
        ),
        (
            "examples/service/wc_delegation_spec.business_context.v1_2.json",
            "schemas/service/nex_wc/delegation_spec.v1_2.schema.json",
        ),
        (
            "examples/service/wc_claimed_work_planning_source.business_context.v2.json",
            "schemas/service/nex_wc/claimed_work_planning_source.v2.schema.json",
        ),
    }


def test_01b1_static_guard_blocks_fixed_values_and_private_sql_in_successor_code() -> None:
    fixed_business_values = (
        "10000.00",
        "1350.20",
        "0.400000",
        "0.600000",
        "5400800",
        "8101200",
    )
    product_paths = (
        ROOT / "services/nex-ae-api/nex_ae_api/project_delegation_planning.py",
        ROOT / "services/nex-ae-api/nex_ae_api/background_planning.py",
        ROOT / "services/nex-ae-api/nex_ae_api/agent_runtime_process.py",
    )
    for path in product_paths:
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in fixed_business_values)

    successor_paths = list(
        (ROOT / "services").glob("**/*m1_transaction_orchestration*.py")
    ) + list((ROOT / "scripts").glob("**/*e2e_fx_01b*.py"))
    forbidden = (
        "golden_a",
        "p8_demo",
        "INSERT INTO ",
        "UPDATE ",
        "DELETE FROM ",
    )
    for path in successor_paths:
        source = path.read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden), path
