from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_ae_api.domain_intent_products import build_domain_intent_activator_registry
from nex_ae_api.finance_golden_a_activation import (
    FINANCE_GOLDEN_A_PROFILE_PATH_ENV,
    FinanceGoldenAActivationError,
    VersionedGoldenAFinanceAuthoritySource,
)
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_CAPABILITY_ID,
    GOLDEN_A_NSL_SKILL_ID,
    bind_golden_a_product_candidate,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    load_product_capability_registry,
)
from nex_ae_api.work_intent import build_work_intent_from_decision
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "deployment/environments/finance-golden-a-vo00.v1.json"
CAPABILITY_REGISTRY_PATH = (
    ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
)
NOW = "2026-10-28T09:00:00Z"


def _profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _product_environ() -> dict[str, str]:
    return {
        FINANCE_GOLDEN_A_PROFILE_PATH_ENV: str(PROFILE_PATH),
        PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(CAPABILITY_REGISTRY_PATH),
    }


def _capability() -> dict:
    registration = load_product_capability_registry(_product_environ()).resolve(
        GOLDEN_A_CAPABILITY_ID, required=True
    )
    assert registration is not None
    return dict(registration.capability)


def _candidate(*, project: str = "PROJECT-A-2") -> dict:
    protected = _profile()["protected_input"]
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": GOLDEN_A_CAPABILITY_ID,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": project,
                "confidence": 0.98,
            }
        ],
        "parameter_candidates": [
            {"name": name, "value": protected[name], "confidence": 0.97}
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
        execution_id="10000000-0000-4000-8000-000000000010",
        source_ref="AE:INTERACTION:gb2-s10",
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
        work_intent_id="20000000-0000-4000-8000-000000000010",
    )


def _rehash(profile: dict) -> dict:
    profile["profile_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in profile.items() if key != "profile_hash"}
    )
    return profile


def test_product_registry_resolves_finance_capability_with_distinct_skill() -> None:
    registry = build_domain_intent_activator_registry(_product_environ())
    registration = registry.resolve(GOLDEN_A_CAPABILITY_ID, required=True)

    assert registration is not None
    assert registration.version == "finance-golden-a.v1"
    assert registration.source_identity.startswith("nex-ae:finance-golden-a:v1:")
    activation = bind_golden_a_product_candidate(
        authority_profile=_profile(), candidate=_candidate(), capability=_capability()
    )
    capability = activation["authoritative_binding"]["capability_ref"]
    assert capability["capability_id"] == GOLDEN_A_CAPABILITY_ID
    assert capability["skill_id"] == GOLDEN_A_NSL_SKILL_ID
    assert capability["capability_id"] != capability["skill_id"]


def test_product_activation_is_tenant_scoped_and_replay_deterministic() -> None:
    registration = build_domain_intent_activator_registry(_product_environ()).resolve(
        GOLDEN_A_CAPABILITY_ID, required=True
    )
    assert registration is not None

    first = registration.activator.activate(
        candidate=_candidate(),
        work_intent=_work_intent(),
        tenant_id="VO00",
        principal_id="employee-1001",
        resolved_at=NOW,
    )
    replay = registration.activator.activate(
        candidate=_candidate(),
        work_intent=first.work_intent,
        tenant_id="VO00",
        principal_id="employee-1001",
        resolved_at=NOW,
    )

    assert first.work_intent == replay.work_intent
    resolved = first.context_resolver.resolve(object())
    assert resolved.project_ref is None
    assert resolved.context_manifest[0]["kind"] == "FINANCE_AUTHORITY_PROFILE"
    assert resolved.context_manifest[0]["content_hash"] == _profile()["profile_hash"]


@pytest.mark.parametrize(
    ("tenant_id", "principal_id", "error_code"),
    [
        ("OTHER", "employee-1001", "FINANCE_AUTHORITY_TENANT_MISMATCH"),
        ("VO00", "employee-9999", "FINANCE_AUTHORITY_PRINCIPAL_MISMATCH"),
    ],
)
def test_product_authority_scope_mismatch_fails_closed(
    tenant_id: str, principal_id: str, error_code: str
) -> None:
    source = VersionedGoldenAFinanceAuthoritySource(_profile())

    with pytest.raises(FinanceGoldenAActivationError) as raised:
        source.resolve(
            tenant_id=tenant_id,
            principal_id=principal_id,
            resolved_at=NOW,
        )
    assert raised.value.error_code == error_code


def test_project_and_account_authority_mismatches_fail_closed() -> None:
    unknown_project = bind_golden_a_product_candidate(
        authority_profile=_profile(),
        candidate=_candidate(project="PROJECT-X"),
        capability=_capability(),
    )
    assert unknown_project["directive"] == "CLARIFICATION_REQUIRED"
    assert unknown_project["failure_code"] == "PROJECT_CANDIDATE_NOT_FOUND"

    damaged = deepcopy(_profile())
    damaged["voucher_line_policy"]["debit_account_id"] = "missing-account"
    with pytest.raises(FinanceGoldenAActivationError) as raised:
        VersionedGoldenAFinanceAuthoritySource(_rehash(damaged))
    assert raised.value.error_code == "FINANCE_AUTHORITY_PROFILE_INVALID"


def test_generic_attachment_has_no_demo_fixture_dependency() -> None:
    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "services/nex-ae-api/nex_ae_api/domain_intent_products.py",
            "services/nex-ae-api/nex_ae_api/finance_golden_a_activation.py",
            "services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py",
        )
    )
    for forbidden in (
        "NEX_AE_DEMO_FIXTURE",
        "NEX_AE_DEMO_BASE_FIXTURE",
        "scripts/smoke/data",
        "scripts/deployment/data",
        "p8_demo_semantic_activation",
    ):
        assert forbidden not in sources

    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    assert FINANCE_GOLDEN_A_PROFILE_PATH_ENV in compose
    assert "NEX_AE_DEMO_GOLDEN_A_ADMISSION_ENABLED" not in compose


def test_product_profile_hash_and_file_admission_fail_closed(tmp_path: Path) -> None:
    invalid = _profile()
    invalid["profile_hash"] = "sha256:" + "0" * 64
    path = tmp_path / "invalid-profile.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(FinanceGoldenAActivationError) as raised:
        build_domain_intent_activator_registry(
            {
                **_product_environ(),
                FINANCE_GOLDEN_A_PROFILE_PATH_ENV: str(path),
            }
        )
    assert raised.value.error_code == "FINANCE_AUTHORITY_PROFILE_INVALID"

    with pytest.raises(FinanceGoldenAActivationError) as raised:
        build_domain_intent_activator_registry(
            {
                **_product_environ(),
                FINANCE_GOLDEN_A_PROFILE_PATH_ENV: str(tmp_path / "missing.json"),
            }
        )
    assert raised.value.error_code == "FINANCE_AUTHORITY_SOURCE_UNAVAILABLE"
