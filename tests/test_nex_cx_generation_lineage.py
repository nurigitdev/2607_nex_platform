from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.generation_lineage import (
    CX_GROUNDED_GENERATION_LINEAGE_SCHEMA_VERSION,
    GroundedGenerationLineageError,
    build_grounded_generation_lineage,
    validate_grounded_generation_lineage,
)
from nex_cx.grounded_prompt import build_grounded_evidence_binding


def _retrieval_package() -> dict:
    return {
        "retrieval_package_id": "retrieval-1365",
        "package_hash": "b" * 64,
        "evidence_items": [
            {
                "evidence_id": "evidence-1",
                "citation_label": "[1]",
                "text": "Owner-private evidence one.",
            },
            {
                "evidence_id": "evidence-2",
                "citation_label": "[2]",
                "text": "Owner-private evidence two.",
            },
        ],
    }


def _mo_payload() -> dict:
    binding = build_grounded_evidence_binding(
        retrieval_package=_retrieval_package(),
        selected_evidence_ids=["evidence-1"],
    )
    return {
        "provider_prompt_package_hash": "a" * 64,
        "metadata": {
            "retrieval_package_id": "retrieval-1365",
            "retrieval_package_hash": "b" * 64,
            "evidence_binding_hash": binding["evidence_binding_hash"],
            "selected_evidence_count": 1,
        },
    }


def _draft(status: str = "VALIDATED") -> dict:
    return {"validation": {"citation_status": status}}


def _repair() -> dict:
    return {
        "repair_schema_version": "cx_citation_repair.v1",
        "attempted": True,
        "attempt_count": 1,
        "max_attempts": 1,
        "trigger_error_code": "cx.citation_required_missing",
        "same_retrieval_package": True,
        "original_provider_prompt_package_hash": "c" * 64,
        "effective_provider_prompt_package_hash": "a" * 64,
        "invalid_output_included": False,
    }


def _build(**overrides) -> dict:
    values = {
        "mo_payload": _mo_payload(),
        "retrieval_package": _retrieval_package(),
        "selected_evidence_ids": ["evidence-1"],
        "structured_draft": _draft(),
        "citation_repair": None,
    }
    values.update(overrides)
    return build_grounded_generation_lineage(**values)


def test_lineage_binds_exact_evidence_without_private_payload() -> None:
    lineage = _build()

    assert lineage["lineage_schema_version"] == (
        CX_GROUNDED_GENERATION_LINEAGE_SCHEMA_VERSION
    )
    assert lineage["retrieval_package_id"] == "retrieval-1365"
    assert lineage["selected_evidence_count"] == 1
    assert lineage["citation_repair_attempted"] is False
    assert lineage["original_provider_prompt_package_hash"] == "a" * 64
    assert lineage["effective_provider_prompt_package_hash"] == "a" * 64
    assert lineage["private_evidence_included"] is False
    assert "Owner-private" not in str(lineage)


def test_lineage_binds_repair_prompt_transition() -> None:
    lineage = _build(citation_repair=_repair())

    assert lineage["citation_repair_attempted"] is True
    assert lineage["citation_repair_attempt_count"] == 1
    assert lineage["original_provider_prompt_package_hash"] == "c" * 64
    assert lineage["effective_provider_prompt_package_hash"] == "a" * 64


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "retrieval_package": {
                    **_retrieval_package(),
                    "evidence_items": [{"evidence_id": "bad"}],
                }
            },
            "evidence binding",
        ),
        ({"mo_payload": {"provider_prompt_package_hash": "a" * 64}}, "metadata"),
        (
            {
                "mo_payload": {
                    **_mo_payload(),
                    "metadata": {
                        **_mo_payload()["metadata"],
                        "retrieval_package_id": "other",
                    },
                }
            },
            "identity",
        ),
        (
            {
                "mo_payload": {
                    **_mo_payload(),
                    "metadata": {
                        **_mo_payload()["metadata"],
                        "evidence_binding_hash": "0" * 64,
                    },
                }
            },
            "binding changed",
        ),
        (
            {
                "mo_payload": {
                    **_mo_payload(),
                    "metadata": {
                        **_mo_payload()["metadata"],
                        "selected_evidence_count": 2,
                    },
                }
            },
            "count changed",
        ),
        ({"structured_draft": _draft("FAILED")}, "did not pass"),
        ({"citation_repair": {}}, "repair lineage"),
        (
            {
                "citation_repair": {
                    **_repair(),
                    "effective_provider_prompt_package_hash": "d" * 64,
                }
            },
            "effective prompt hash changed",
        ),
    ],
)
def test_lineage_builder_fails_closed_on_drift(overrides, message) -> None:
    with pytest.raises(GroundedGenerationLineageError, match=message):
        _build(**overrides)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(lineage_schema_version="old"),
        lambda value: value.update(retrieval_package_id=""),
        lambda value: value.update(retrieval_package_hash="bad"),
        lambda value: value.update(evidence_binding_hash="bad"),
        lambda value: value.update(original_provider_prompt_package_hash="bad"),
        lambda value: value.update(effective_provider_prompt_package_hash="bad"),
        lambda value: value.update(selected_evidence_count=True),
        lambda value: value.update(selected_evidence_count=0),
        lambda value: value.update(citation_validation_status="FAILED"),
        lambda value: value.update(citation_repair_attempted="yes"),
        lambda value: value.update(
            citation_repair_attempted=True,
            citation_repair_attempt_count=0,
        ),
        lambda value: value.update(effective_provider_prompt_package_hash="d" * 64),
        lambda value: value.update(same_retrieval_package=False),
        lambda value: value.update(private_evidence_included=True),
    ],
)
def test_lineage_validator_rejects_invalid_projection(mutation) -> None:
    lineage = deepcopy(_build())
    mutation(lineage)

    with pytest.raises(GroundedGenerationLineageError):
        validate_grounded_generation_lineage(lineage)


def test_lineage_validator_rejects_non_object() -> None:
    with pytest.raises(GroundedGenerationLineageError):
        validate_grounded_generation_lineage([])
