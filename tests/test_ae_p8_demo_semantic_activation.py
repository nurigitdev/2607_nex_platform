from __future__ import annotations

from pathlib import Path

import pytest
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID
from nex_ae_api.p8_demo_semantic_activation import (
    P8_DEMO_GOLDEN_A_ADMISSION_ENV,
    build_p8_demo_intent_activators,
)
from nex_ae_api.work_intent import build_work_intent_from_decision
from nex_runtime.demo_fixture import load_demo_business_fixture
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-26T04:00:00Z"


def _environment() -> dict[str, str]:
    return {
        P8_DEMO_GOLDEN_A_ADMISSION_ENV: "true",
        "NEX_AE_DEMO_FIXTURE": str(
            ROOT / "scripts/deployment/data/p8_demo_vo00_fixture.v1.json"
        ),
        "NEX_AE_DEMO_BASE_FIXTURE": str(
            ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json"
        ),
    }


def _candidate(fixture: dict) -> dict:
    scenario = fixture["scenario"]
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": GOLDEN_A_CAPABILITY_ID,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": "PROJECT-A-2",
                "confidence": 0.98,
            }
        ],
        "parameter_candidates": [
            {"name": name, "value": scenario[name], "confidence": 0.97}
            for name in (
                "amount",
                "currency",
                "transaction_date",
                "voucher_type",
                "economic_category",
                "settlement_method",
            )
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.98,
    }


def _work_intent() -> dict:
    return build_work_intent_from_decision(
        execution_id="10000000-0000-4000-8000-000000000001",
        source_ref="AE:INTERACTION:p8-demo",
        actor_ref="OA:SUBJECT:employee-1001",
        received_at=NOW,
        intent_decision={
            "intent_decision_schema_version": "ae_intent_decision.v1",
            "intent_label": GOLDEN_A_CAPABILITY_ID,
            "execution_mode": "GENERAL_ANSWER",
            "confidence": 0.98,
            "raw_prompt_included": False,
            "decision_hash": "a" * 64,
        },
        input_context_hash=semantic_sha256_hash_ref({"prompt": "redacted"}),
        work_intent_id="20000000-0000-4000-8000-000000000001",
    )


def test_demo_golden_a_activation_is_explicit_and_deterministic() -> None:
    assert build_p8_demo_intent_activators({}) == {}
    with pytest.raises(ValueError, match="NEX_AE_DEMO_FIXTURE"):
        build_p8_demo_intent_activators(
            {P8_DEMO_GOLDEN_A_ADMISSION_ENV: "true"}
        )

    activator = build_p8_demo_intent_activators(_environment())[
        GOLDEN_A_CAPABILITY_ID
    ]
    _, fixture = load_demo_business_fixture(
        Path(_environment()["NEX_AE_DEMO_FIXTURE"]),
        base_fixture_path=Path(_environment()["NEX_AE_DEMO_BASE_FIXTURE"]),
    )
    first = activator.activate(
        candidate=_candidate(fixture),
        work_intent=_work_intent(),
        principal_id="employee-1001",
        resolved_at=NOW,
    )
    replay = activator.activate(
        candidate=_candidate(fixture),
        work_intent=first.work_intent,
        principal_id="employee-1001",
        resolved_at=NOW,
    )

    assert first.work_intent == replay.work_intent
    assert first.work_intent["required_capability_hints"] == [
        GOLDEN_A_CAPABILITY_ID
    ]
    assert first.work_intent["parameter_candidates"]
    resolved = first.context_resolver.resolve(object())
    assert resolved.project_ref is None
    assert resolved.authority_ref == "OA:SUBJECT:employee-1001"
