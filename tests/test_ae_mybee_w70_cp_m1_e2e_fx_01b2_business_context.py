from __future__ import annotations

import copy
import json
from pathlib import Path

import nex_ae_api.business_request_context as context_module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.business_request_context import (
    BusinessRequestContextError,
    admit_business_request_context,
    validate_business_request_context,
)
from nex_ae_api.intent_policy import resolve_validated_intent_candidate
from nex_ae_api.work_intent import (
    SqlAlchemyWorkIntentRepository,
    WorkIntentError,
    build_work_intent_from_decision,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from referencing import Registry, Resource
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_SCHEMA = (
    ROOT
    / "contracts/schemas/service/nex_ae_api/business_request_context.v1.schema.json"
)
WORK_INTENT_SCHEMA = (
    ROOT / "contracts/schemas/service/nex_ae_api/work_intent.v1_2.schema.json"
)

EXECUTION_ID = "10000000-0000-4000-8000-000000000201"
WORK_INTENT_ID = "20000000-0000-4000-8000-000000000201"
PROMPT_VERSION_ID = "30000000-0000-4000-8000-000000000201"
SOURCE_REF = "AE:INTERACTION:40000000-0000-4000-8000-000000000201"
INPUT_CONTEXT_HASH = "sha256:" + "a" * 64
NOW = "2026-11-16T01:00:00Z"
PROJECT_A = "VO00D260101"
PROJECT_B = "VO00D260102"


def _candidate(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": PROJECT_A,
                "confidence": 0.98,
            }
        ],
        "parameter_candidates": [
            {"name": "company_selector", "value": "NURIVOICE", "confidence": 0.99},
            {
                "name": "primary_project_code",
                "value": PROJECT_A,
                "confidence": 0.99,
            },
            {
                "name": "document_subject",
                "value": "Quarterly customer workshop expense",
                "confidence": 0.97,
            },
            {
                "name": "counterparty_selector",
                "value": "Workshop Vendor",
                "confidence": 0.96,
            },
            {"name": "amount", "value": "10000.00", "confidence": 0.99},
            {"name": "currency", "value": "USD", "confidence": 0.99},
            {
                "name": "recognition_date",
                "value": "2026-11-16",
                "confidence": 0.98,
            },
            {
                "name": "description",
                "value": "Allocate the approved expense to two Projects.",
                "confidence": 0.95,
            },
            {
                "name": "allocation_project_code_1",
                "value": PROJECT_A,
                "confidence": 0.99,
            },
            {"name": "allocation_ratio_1", "value": "0.400000", "confidence": 0.99},
            {
                "name": "allocation_project_code_2",
                "value": PROJECT_B,
                "confidence": 0.99,
            },
            {"name": "allocation_ratio_2", "value": "0.600000", "confidence": 0.99},
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.97,
    }
    record.update(overrides)
    return record


def _intent(candidate: dict[str, object] | None = None, **overrides: object) -> dict:
    selected = candidate or _candidate()
    values = {
        "execution_id": EXECUTION_ID,
        "source_ref": SOURCE_REF,
        "actor_ref": "OA:SUBJECT:employee-100",
        "received_at": NOW,
        "intent_decision": resolve_validated_intent_candidate(selected),
        "input_context_hash": INPUT_CONTEXT_HASH,
        "work_intent_id": WORK_INTENT_ID,
        "prompt_provenance": {
            "prompt_binding_key": "ae.intent_resolution.default",
            "prompt_template_version_id": PROMPT_VERSION_ID,
            "prompt_content_sha256": "b" * 64,
            "rendered_prompt_hash": "c" * 64,
            "model_profile": "generation-default",
            "model_ref": "provider-neutral/revision-bound",
        },
        "intent_candidate": selected,
        "intent_candidate_hash": semantic_sha256_hash_ref(selected),
    }
    values.update(overrides)
    return build_work_intent_from_decision(**values)


def _validator(path: Path) -> Draft202012Validator:
    context_schema = json.loads(CONTEXT_SCHEMA.read_text(encoding="utf-8"))
    work_intent_schema = json.loads(WORK_INTENT_SCHEMA.read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        (
            (context_schema["$id"], Resource.from_contents(context_schema)),
            (work_intent_schema["$id"], Resource.from_contents(work_intent_schema)),
        )
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(
        schema, registry=registry, format_checker=FormatChecker()
    )


def _factory() -> sessionmaker:
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(
            text("""
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
        """)
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _replace_parameter(
    candidate: dict[str, object], name: str, value: object
) -> dict[str, object]:
    changed = copy.deepcopy(candidate)
    for item in changed["parameter_candidates"]:
        if item["name"] == name:
            item["value"] = value
            break
    return changed


def _admit(
    candidate: object,
    *,
    candidate_hash: str | None = None,
    source_prompt_ref: str = SOURCE_REF,
    input_context_hash: str = INPUT_CONTEXT_HASH,
    model_profile: str | None = "generation-default",
    model_ref: str | None = "provider-neutral/revision-bound",
    attachment_manifest_hash: str | None = None,
):
    return admit_business_request_context(
        candidate=candidate,
        candidate_hash=(
            semantic_sha256_hash_ref(candidate)
            if candidate_hash is None and isinstance(candidate, dict)
            else candidate_hash or "sha256:" + "f" * 64
        ),
        source_prompt_ref=source_prompt_ref,
        input_context_hash=input_context_hash,
        model_profile=model_profile,
        model_ref=model_ref,
        attachment_manifest_hash=attachment_manifest_hash,
    )


def _rehash_context(context: dict) -> dict:
    context["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in context.items() if key != "context_hash"}
    )
    return context


def test_01b2_builds_contract_valid_hash_bound_work_intent_v1_2() -> None:
    record = _intent()

    _validator(CONTEXT_SCHEMA).validate(record["business_request_context"])
    _validator(WORK_INTENT_SCHEMA).validate(record)
    assert record["schema_version"] == "1.2"
    assert (
        record["business_context_hash"]
        == record["business_request_context"]["context_hash"]
    )
    assert record["business_request_context"]["candidate_provenance"] == {
        "intent_candidate_hash": semantic_sha256_hash_ref(_candidate()),
        "input_context_hash": INPUT_CONTEXT_HASH,
        "model_profile": "generation-default",
        "model_ref": "provider-neutral/revision-bound",
    }
    assert "10000.00" not in record["goal"]
    assert record["parameter_candidates"][0]["source"] == "MODEL_CANDIDATE"


def test_01b2_different_requests_have_distinct_context_and_intent_hashes() -> None:
    first = _intent()
    second_candidate = _replace_parameter(_candidate(), "amount", "2500.00")
    second = _intent(
        second_candidate,
        work_intent_id="20000000-0000-4000-8000-000000000202",
    )

    assert first["business_context_hash"] != second["business_context_hash"]
    assert first["intent_hash"] != second["intent_hash"]


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("amount", "12.345"),
        ("amount", "NaN"),
        ("currency", "US"),
        ("recognition_date", "2026-02-30"),
        ("allocation_ratio_2", "0.500000"),
    ),
)
def test_01b2_rejects_malformed_business_values(name: str, value: object) -> None:
    candidate = _replace_parameter(_candidate(), name, value)

    with pytest.raises(WorkIntentError) as raised:
        _intent(candidate)

    assert raised.value.error_code == "ae.business_context_invalid"


def test_01b2_admits_multiple_allocation_selectors_by_typed_primary_identity() -> None:
    candidate = _candidate(
        entity_selectors=[
            *_candidate()["entity_selectors"],
            {
                "selector_id": "E2",
                "selector_type": "QUERY_TERM",
                "value": PROJECT_B,
                "confidence": 0.97,
            },
        ]
    )

    admitted = _admit(candidate)

    assert [item["raw_text"] for item in admitted.entity_selectors] == [PROJECT_A]
    parameters = {item["name"]: item["value"] for item in admitted.parameter_candidates}
    assert parameters["primary_project_code"] == PROJECT_A


def test_01b2_rejects_primary_project_identity_conflicts_and_authority_parameter() -> (
    None
):
    cases = []
    missing_primary_selector = copy.deepcopy(_candidate())
    missing_primary_selector["entity_selectors"][0]["value"] = PROJECT_B
    cases.append(missing_primary_selector)
    unknown_selector = copy.deepcopy(_candidate())
    unknown_selector["entity_selectors"].append(
        {
            "selector_id": "E2",
            "selector_type": "QUERY_TERM",
            "value": "VO00D260103",
            "confidence": 0.97,
        }
    )
    cases.append(unknown_selector)
    duplicate_primary = copy.deepcopy(_candidate())
    duplicate_primary["entity_selectors"].append(
        {
            "selector_id": "E2",
            "selector_type": "QUERY_TERM",
            "value": PROJECT_A,
            "confidence": 0.97,
        }
    )
    cases.append(duplicate_primary)
    cases.append(
        _replace_parameter(_candidate(), "primary_project_code", "VO00D260103")
    )

    for ambiguous in cases:
        with pytest.raises(WorkIntentError) as project_error:
            _intent(ambiguous)
        assert project_error.value.error_code == "ae.business_context_project_ambiguous"

    authority = copy.deepcopy(_candidate())
    authority["parameter_candidates"].append(
        {"name": "account_id", "value": "model-account", "confidence": 0.9}
    )
    with pytest.raises(WorkIntentError) as authority_error:
        _intent(authority)
    assert authority_error.value.error_code == "ae.business_context_authority_forbidden"


def test_01b2_rejects_tamper_and_context_size_overflow(monkeypatch) -> None:
    context = copy.deepcopy(_intent()["business_request_context"])
    context["transaction"]["amount"] = "1.00"
    with pytest.raises(BusinessRequestContextError) as tampered:
        validate_business_request_context(context)
    assert tampered.value.error_code == "ae.business_context_hash_mismatch"

    valid = _intent()["business_request_context"]
    monkeypatch.setattr(context_module, "BUSINESS_CONTEXT_MAX_BYTES", 128)
    with pytest.raises(BusinessRequestContextError) as oversized:
        validate_business_request_context(valid)
    assert oversized.value.error_code == "ae.business_context_bounds_exceeded"


def test_01b2_requires_candidate_lineage_and_persists_exact_v1_2_json() -> None:
    selected = _candidate()
    decision = resolve_validated_intent_candidate(selected)
    with pytest.raises(WorkIntentError) as missing:
        build_work_intent_from_decision(
            execution_id=EXECUTION_ID,
            source_ref=SOURCE_REF,
            actor_ref="OA:SUBJECT:employee-100",
            received_at=NOW,
            intent_decision=decision,
            input_context_hash=INPUT_CONTEXT_HASH,
            work_intent_id=WORK_INTENT_ID,
        )
    assert missing.value.error_code == "ae.work_intent_invalid"

    repository = SqlAlchemyWorkIntentRepository(_factory())
    record = _intent()
    saved = repository.save(tenant_id="VO00", work_intent=record, created_at=NOW)
    assert saved == record
    assert repository.get(tenant_id="VO00", work_intent_id=WORK_INTENT_ID) == record


def test_01b2_legacy_v1_1_replay_remains_accepted() -> None:
    decision = resolve_validated_intent_candidate(
        _candidate(
            intent_label="GENERAL.QUESTION.ANSWER",
            entity_selectors=[],
            parameter_candidates=[],
        )
    )
    legacy = build_work_intent_from_decision(
        execution_id=EXECUTION_ID,
        source_ref=SOURCE_REF,
        actor_ref="OA:SUBJECT:employee-100",
        received_at=NOW,
        intent_decision=decision,
        input_context_hash=INPUT_CONTEXT_HASH,
        work_intent_id=WORK_INTENT_ID,
    )
    repository = SqlAlchemyWorkIntentRepository(_factory())

    assert legacy["schema_version"] == "1.1"
    assert (
        repository.save(tenant_id="VO00", work_intent=legacy, created_at=NOW) == legacy
    )


def test_01b2_admission_preserves_optional_attachment_and_null_model_lineage() -> None:
    attachment_hash = "sha256:" + "d" * 64
    admitted = _admit(
        _candidate(),
        model_profile=None,
        model_ref=None,
        attachment_manifest_hash=attachment_hash,
    )

    assert admitted.context["document"]["attachment_manifest_hash"] == attachment_hash
    assert admitted.context["candidate_provenance"]["model_profile"] is None
    assert admitted.context["candidate_provenance"]["model_ref"] is None


@pytest.mark.parametrize(
    "candidate",
    (
        None,
        {},
        _candidate(schema_version="unsupported"),
        _candidate(parameter_candidates="invalid"),
        _candidate(parameter_candidates=[{"name": "amount"}]),
        _candidate(
            parameter_candidates=[
                *_candidate()["parameter_candidates"],
                {"name": "amount", "value": "1.00", "confidence": 0.9},
            ]
        ),
        _candidate(
            parameter_candidates=[
                item
                for item in _candidate()["parameter_candidates"]
                if item["name"] != "description"
            ]
        ),
        _candidate(entity_selectors="invalid"),
        _candidate(
            entity_selectors=[
                {
                    "selector_id": "invalid",
                    "selector_type": "QUERY_TERM",
                    "value": PROJECT_A,
                    "confidence": 0.9,
                }
            ]
        ),
    ),
)
def test_01b2_rejects_invalid_candidate_shapes(candidate: object) -> None:
    with pytest.raises(BusinessRequestContextError):
        _admit(candidate)


def test_01b2_rejects_candidate_hash_source_and_lineage_tamper() -> None:
    cases = (
        {"candidate_hash": "sha256:" + "0" * 64},
        {"source_prompt_ref": "WC:WORK_ITEM:not-an-interaction"},
        {"input_context_hash": "invalid"},
        {"model_profile": "x" * 129},
        {"model_ref": "x" * 257},
        {"attachment_manifest_hash": "invalid"},
    )
    for values in cases:
        with pytest.raises(BusinessRequestContextError):
            _admit(_candidate(), **values)


def test_01b2_rejects_allocation_shape_and_project_conflicts() -> None:
    missing_pair = copy.deepcopy(_candidate())
    missing_pair["parameter_candidates"] = [
        item
        for item in missing_pair["parameter_candidates"]
        if item["name"] != "allocation_ratio_2"
    ]
    non_contiguous = copy.deepcopy(_candidate())
    for item in non_contiguous["parameter_candidates"]:
        if item["name"].endswith("_2"):
            item["name"] = item["name"].removesuffix("_2") + "_3"
    duplicate_project = _replace_parameter(
        _candidate(), "allocation_project_code_2", PROJECT_A
    )
    delegated_project_missing = _replace_parameter(
        _candidate(), "allocation_project_code_1", "VO00D260103"
    )

    for candidate in (
        missing_pair,
        non_contiguous,
        duplicate_project,
        delegated_project_missing,
    ):
        with pytest.raises(BusinessRequestContextError):
            _admit(candidate)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.pop("company_selector"),
        lambda value: value.update(schema_version="unsupported"),
        lambda value: value["company_selector"].update(kind="AUTHORITY"),
        lambda value: value["company_selector"].update(value=""),
        lambda value: value["document"].pop("subject_ref"),
        lambda value: value["document"].update(document_type="OTHER"),
        lambda value: value["document"].update(subject_revision=True),
        lambda value: value["document"].update(content_hash="invalid"),
        lambda value: value["document"].update(attachment_manifest_hash="invalid"),
        lambda value: value["transaction"].pop("description"),
        lambda value: value["transaction"].update(amount="01.00"),
        lambda value: value["transaction"].update(currency="usd"),
        lambda value: value["transaction"].update(recognition_date="invalid"),
        lambda value: value.update(requested_allocation=[]),
        lambda value: value["requested_allocation"][0].pop("ratio"),
        lambda value: value["requested_allocation"].append(
            copy.deepcopy(value["requested_allocation"][0])
        ),
        lambda value: value["requested_allocation"][0].update(ratio="0.4"),
        lambda value: value["requested_allocation"][1].update(ratio="0.500000"),
        lambda value: value["candidate_provenance"].pop("model_ref"),
        lambda value: value["candidate_provenance"].update(
            intent_candidate_hash="invalid"
        ),
        lambda value: value["candidate_provenance"].update(model_profile="x" * 129),
        lambda value: value.update(source_prompt_ref="invalid"),
    ),
)
def test_01b2_context_validation_fails_closed_for_invalid_shapes(mutation) -> None:
    context = copy.deepcopy(_intent()["business_request_context"])
    mutation(context)
    _rehash_context(context)

    with pytest.raises(BusinessRequestContextError):
        validate_business_request_context(context)


def test_01b2_context_validator_rejects_non_mapping_and_error_is_readable() -> None:
    with pytest.raises(BusinessRequestContextError) as raised:
        validate_business_request_context(None)

    assert str(raised.value) == "BusinessRequestContext must be an object."


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("amount", True),
        ("amount", "not-a-decimal"),
        ("amount", "10000000000000000.00"),
        ("amount", "1E+999999"),
        ("currency", 123),
        ("recognition_date", 20261116),
        ("allocation_project_code_1", 123),
        ("allocation_project_code_1", "not-a-project"),
        ("allocation_ratio_1", True),
        ("allocation_ratio_1", "not-a-ratio"),
        ("allocation_ratio_1", "1E+999999"),
        ("allocation_ratio_1", "0.1234567"),
        ("allocation_ratio_1", "1.100000"),
    ),
)
def test_01b2_numeric_and_identifier_bounds_fail_closed(
    name: str, value: object
) -> None:
    with pytest.raises(BusinessRequestContextError):
        _admit(_replace_parameter(_candidate(), name, value))


def test_01b2_parameter_names_and_confidence_fail_closed() -> None:
    invalid_name = copy.deepcopy(_candidate())
    invalid_name["parameter_candidates"][0]["name"] = None
    invalid_confidence = copy.deepcopy(_candidate())
    invalid_confidence["parameter_candidates"][0]["confidence"] = True

    for candidate in (invalid_name, invalid_confidence):
        with pytest.raises(BusinessRequestContextError):
            _admit(candidate)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(company_selector=None),
        lambda value: value.update(candidate_provenance=None),
        lambda value: value["transaction"].update(recognition_date="20261116"),
        lambda value: value["transaction"].update(counterparty_selector=""),
        lambda value: value["transaction"].update(description=""),
    ),
)
def test_01b2_context_scalar_canonicalization_fails_closed(mutation) -> None:
    context = copy.deepcopy(_intent()["business_request_context"])
    mutation(context)
    _rehash_context(context)

    with pytest.raises(BusinessRequestContextError):
        validate_business_request_context(context)
