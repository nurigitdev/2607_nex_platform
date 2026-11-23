from __future__ import annotations

import copy

import pytest

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_runtime.work_result_business_projection import (
    WORK_RESULT_BUSINESS_PROJECTION_SCHEMA_VERSION,
    WorkResultBusinessProjectionError,
    build_work_result_business_projection,
    validate_work_result_business_projection,
)

AGENT_RESULT_HASH = semantic_sha256_hash_ref({"agent_result": "authority"})


def _build(**overrides):
    values = {
        "source_agent_result_hash": AGENT_RESULT_HASH,
        "business_object_refs": [
            {"entity_type": "VOUCHER", "entity_id": "voucher-1"}
        ],
        "external_refs": ["z-ref", "a-ref", "a-ref"],
        "business_summary": {"result_type": "voucher", "amount": "10.00"},
    }
    values.update(overrides)
    return build_work_result_business_projection(**values)


def test_ca00b_runtime_projection_is_canonical_and_hash_bound() -> None:
    projection = _build()
    assert projection["schema_version"] == (
        WORK_RESULT_BUSINESS_PROJECTION_SCHEMA_VERSION
    )
    assert projection["external_refs"] == ["a-ref", "z-ref"]
    assert validate_work_result_business_projection(projection) == projection

    tampered = copy.deepcopy(projection)
    tampered["business_summary"]["amount"] = "11.00"
    with pytest.raises(WorkResultBusinessProjectionError, match="hash"):
        validate_work_result_business_projection(tampered)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "must be an object"),
        ({}, "fields are invalid"),
    ],
)
def test_ca00b_runtime_projection_rejects_invalid_envelopes(
    value, message: str
) -> None:
    with pytest.raises(WorkResultBusinessProjectionError, match=message):
        validate_work_result_business_projection(value)

    projection = _build()
    projection["schema_version"] = "unknown"
    with pytest.raises(WorkResultBusinessProjectionError, match="schema version"):
        validate_work_result_business_projection(projection)

    projection = _build()
    projection["source_agent_result_hash"] = "invalid"
    with pytest.raises(WorkResultBusinessProjectionError):
        validate_work_result_business_projection(projection)


@pytest.mark.parametrize(
    ("refs", "message"),
    [
        ("not-an-array", "must be an array"),
        ([{"entity_type": "A"}], "invalid entity reference"),
        ([{"entity_type": "", "entity_id": "id"}], "text value"),
        (
            [
                {"entity_type": "A", "entity_id": "id"},
                {"entity_type": "A", "entity_id": "id"},
            ],
            "duplicate",
        ),
        (
            [{"entity_type": "A", "entity_id": str(index)} for index in range(33)],
            "32-item",
        ),
    ],
)
def test_ca00b_runtime_projection_rejects_invalid_business_refs(
    refs, message: str
) -> None:
    with pytest.raises(WorkResultBusinessProjectionError, match=message):
        _build(business_object_refs=refs)


@pytest.mark.parametrize(
    ("refs", "message"),
    [
        ("not-an-array", "must be an array"),
        ([""], "text value"),
        ([str(index) for index in range(65)], "64-item"),
    ],
)
def test_ca00b_runtime_projection_rejects_invalid_external_refs(
    refs, message: str
) -> None:
    with pytest.raises(WorkResultBusinessProjectionError, match=message):
        _build(external_refs=refs)


@pytest.mark.parametrize(
    ("summary", "message"),
    [
        ("not-an-object", "object or null"),
        ({"unsupported": {"set"}}, "canonical JSON"),
        ({"large": "x" * 32_769}, "32768-byte"),
    ],
)
def test_ca00b_runtime_projection_rejects_invalid_summaries(
    summary, message: str
) -> None:
    with pytest.raises(WorkResultBusinessProjectionError, match=message):
        _build(business_summary=summary)


def test_ca00b_runtime_projection_accepts_null_summary_and_copies_input() -> None:
    refs = [{"entity_type": " B ", "entity_id": " 2 "}]
    projection = _build(
        business_object_refs=refs,
        external_refs=[],
        business_summary=None,
    )
    refs[0]["entity_id"] = "changed"
    assert projection["business_object_refs"] == [
        {"entity_type": "B", "entity_id": "2"}
    ]
    assert projection["business_summary"] is None
