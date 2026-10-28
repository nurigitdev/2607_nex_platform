from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
)
from nex_ae_api.planning_capabilities import DEFAULT_P5_CAPABILITIES
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    ProductCapabilityRegistry,
    ProductCapabilityRegistryError,
    load_product_capability_registry,
)
from nex_ae_api.semantic_candidate_admission import SemanticCandidateAdmissionRuntime
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
PROFILE_PATH = ROOT / "deployment/environments/finance-golden-a-vo00.v1.json"


def _registry_payload() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _profile_payload() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _environ() -> dict[str, str]:
    return {
        PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(REGISTRY_PATH),
        FINANCE_GOLDEN_A_PROFILE_PATH_ENV: str(PROFILE_PATH),
    }


def _write_registry(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _rehash_registry(payload: dict, *, registration: bool = False) -> dict:
    if registration:
        item = payload["registrations"][0]
        item["registration_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in item.items() if key != "registration_hash"}
        )
    payload["registry_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in payload.items() if key != "registry_hash"}
    )
    return payload


def _assert_registry_invalid(tmp_path: Path, payload: object) -> None:
    path = _write_registry(tmp_path, payload)
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(path)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_INVALID"


def test_versioned_registry_is_canonical_capability_and_skill_source() -> None:
    registry = load_product_capability_registry(_environ())
    registration = registry.resolve(GOLDEN_A_CAPABILITY_ID, required=True)

    assert registration is not None
    assert registry.registry_id == "ae-product-capabilities-golden-a"
    assert registry.registry_version == 1
    validate_hash_ref(registry.registry_hash)
    validate_hash_ref(registration.registration_hash)
    assert registration.capability_id == GOLDEN_A_CAPABILITY_ID
    assert registration.capability_version == "1.1.0"
    assert registration.skill_artifact["skill_id"] == GOLDEN_A_NSL_SKILL_ID
    assert registration.capability_id != registration.skill_artifact["skill_id"]
    assert registration.skill_artifact["bundle_id"] == (
        "nex-product-nsl-v0.2.1-finance-voucher-draft-v1"
    )
    assert registration.source_identity == registry.source_identity
    assert registration.to_projection()["registration_hash"] == (
        registration.registration_hash
    )


def test_registry_merge_supplies_product_capability_to_semantic_fallback() -> None:
    registry = load_product_capability_registry(_environ())
    captured: dict[str, object] = {}

    class _Capabilities:
        def get_latest(self, *, tenant_id: str):
            assert tenant_id == "VO00"

    class _Service:
        capabilities = _Capabilities()
        product_capability_registry = registry
        clock = staticmethod(lambda: datetime(2026, 10, 28, tzinfo=UTC))

        @staticmethod
        def admit_and_compile(request):
            captured["snapshot"] = request.capability_snapshot
            return SimpleNamespace(
                status="CANDIDATE_BLOCKED",
                agent_execution_id=None,
            )

    runtime = SemanticCandidateAdmissionRuntime(
        mode="required",
        available=True,
        service=_Service(),  # type: ignore[arg-type]
    )
    runtime.admit_chat(
        payload={
            "tenant_id": "VO00",
            "owner_user_id": "employee-1001",
            "interaction_id": "10000000-0000-4000-8000-000000000001",
            "workspace_id": "20000000-0000-4000-8000-000000000001",
            "conversation_id": "30000000-0000-4000-8000-000000000001",
            "user_message": "전표 초안을 생성해 줘.",
        },
        runtime_policy={
            "compatibility_rule": {
                "rule_id": "ae.compatibility.general-answer",
                "rule_version": "v1",
                "rule_hash": "a" * 64,
            },
            "intent_decision": {
                "retrieval_required": False,
                "execution_mode": "GENERAL_ANSWER",
            },
        },
        retrieval_package=None,
        request_id="request-a",
        trace_id="trace-a",
    )

    snapshot = captured["snapshot"]
    assert isinstance(snapshot, dict)
    assert {item["capability_id"] for item in snapshot["capabilities"]} == {
        "AE.CHAT.COMPATIBILITY",
        "AE.RESULT.REPORT",
        GOLDEN_A_CAPABILITY_ID,
    }


def test_business_authority_profile_contains_no_capability_existence_fact() -> None:
    profile = _profile_payload()

    assert "admission" not in profile
    assert GOLDEN_A_CAPABILITY_ID not in json.dumps(profile, sort_keys=True)
    assert GOLDEN_A_NSL_SKILL_ID not in json.dumps(profile, sort_keys=True)
    VersionedGoldenAFinanceAuthoritySource(profile)


def test_profile_cannot_reintroduce_capability_admission() -> None:
    profile = _profile_payload()
    profile["admission"] = {"capability_id": GOLDEN_A_CAPABILITY_ID}
    profile["profile_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in profile.items() if key != "profile_hash"}
    )

    with pytest.raises(FinanceGoldenAActivationError) as raised:
        VersionedGoldenAFinanceAuthoritySource(profile)
    assert raised.value.error_code == "FINANCE_AUTHORITY_PROFILE_INVALID"


def test_demo_fixture_mutation_cannot_change_registered_capability() -> None:
    fixture_path = ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["admission"]["skill_id"] = "FINANCE.UNTRUSTED_SKILL"

    registration = load_product_capability_registry(_environ()).resolve(
        GOLDEN_A_CAPABILITY_ID, required=True
    )
    assert registration is not None
    assert registration.skill_artifact["skill_id"] == GOLDEN_A_NSL_SKILL_ID
    assert fixture["admission"]["skill_id"] != registration.skill_artifact["skill_id"]

    source = (
        ROOT / "scripts/deployment/run_p8_demo_s11_chairman_golden_journey.py"
    ).read_text(encoding="utf-8")
    activation_source = source[source.index("def _activate_golden_a_capability") :]
    assert "load_demo_business_fixture" not in activation_source
    assert "p8_golden_a_fixture" not in activation_source
    assert "PRODUCT_CAPABILITY_REGISTRY_PATH_ENV" in activation_source


def test_profile_without_registry_fails_closed() -> None:
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        build_domain_intent_activator_registry(
            {FINANCE_GOLDEN_A_PROFILE_PATH_ENV: str(PROFILE_PATH)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REQUIRED"


def test_empty_registry_is_safe_and_required_lookup_fails_closed() -> None:
    registry = ProductCapabilityRegistry()

    assert registry.registrations == ()
    assert registry.resolve(GOLDEN_A_CAPABILITY_ID, required=False) is None
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        registry.resolve(GOLDEN_A_CAPABILITY_ID, required=True)
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REQUIRED"


def test_registry_constructor_rejects_invalid_and_duplicate_entries() -> None:
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        ProductCapabilityRegistry((object(),))  # type: ignore[arg-type]
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRATION_INVALID"

    registry = load_product_capability_registry(_environ())
    registration = registry.registrations[0]
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        ProductCapabilityRegistry((registration, registration))
    assert raised.value.error_code == "PRODUCT_CAPABILITY_DUPLICATE"


def test_registry_file_and_content_hash_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(tmp_path / "missing.json")}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_UNAVAILABLE"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(malformed)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_UNAVAILABLE"

    damaged = _registry_payload()
    damaged["registry_id"] = "tampered"
    path = _write_registry(tmp_path, damaged)
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(path)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_INVALID"


@pytest.mark.parametrize(
    "mutation",
    (
        "non_object",
        "fields",
        "schema",
        "version_zero",
        "version_bool",
        "registrations_empty",
        "registrations_object",
        "hash_invalid",
        "registry_id_whitespace",
    ),
)
def test_registry_contract_shape_failures_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    payload: object = deepcopy(_registry_payload())
    if mutation == "non_object":
        payload = []
    else:
        assert isinstance(payload, dict)
        if mutation == "fields":
            payload["unexpected"] = True
        elif mutation == "schema":
            payload["schema_version"] = "unsupported"
        elif mutation == "version_zero":
            payload["registry_version"] = 0
        elif mutation == "version_bool":
            payload["registry_version"] = True
        elif mutation == "registrations_empty":
            payload["registrations"] = []
        elif mutation == "registrations_object":
            payload["registrations"] = {}
        elif mutation == "hash_invalid":
            payload["registry_hash"] = "invalid"
        elif mutation == "registry_id_whitespace":
            payload["registry_id"] = " invalid "
    _assert_registry_invalid(tmp_path, payload)


def test_registration_contract_shape_failures_are_rejected(tmp_path: Path) -> None:
    cases: list[dict] = []

    non_mapping = deepcopy(_registry_payload())
    non_mapping["registrations"] = [None]
    cases.append(_rehash_registry(non_mapping))

    non_local = deepcopy(_registry_payload())
    non_local["registrations"][0]["capability"] = deepcopy(
        DEFAULT_P5_CAPABILITIES[0]
    )
    cases.append(_rehash_registry(non_local, registration=True))

    bad_artifact = deepcopy(_registry_payload())
    bad_artifact["registrations"][0]["skill_artifact"] = {}
    cases.append(_rehash_registry(bad_artifact, registration=True))

    bad_skill_hash = deepcopy(_registry_payload())
    bad_skill_hash["registrations"][0]["skill_artifact"][
        "skill_semantic_hash"
    ] = "invalid"
    cases.append(_rehash_registry(bad_skill_hash, registration=True))

    bad_registration_hash = deepcopy(_registry_payload())
    bad_registration_hash["registrations"][0]["registration_hash"] = "invalid"
    cases.append(_rehash_registry(bad_registration_hash))

    bad_text = deepcopy(_registry_payload())
    bad_text["registrations"][0]["skill_artifact"]["bundle_id"] = " invalid "
    cases.append(_rehash_registry(bad_text, registration=True))

    for index, payload in enumerate(cases):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        _assert_registry_invalid(case_dir, payload)


def test_registration_file_requires_canonical_capability_order(tmp_path: Path) -> None:
    payload = deepcopy(_registry_payload())
    second = deepcopy(payload["registrations"][0])
    capability = second["capability"]
    capability["capability_id"] = "ZETA.TEST"
    capability["capability_version"] = "1.0"
    binding = capability["local_skill_binding"]
    binding["capability_id"] = "ZETA.TEST"
    binding["skill_id"] = "ZETA.SKILL"
    binding["exact_skill_version"] = "1.0"
    artifact = second["skill_artifact"]
    artifact["skill_id"] = "ZETA.SKILL"
    artifact["exact_skill_version"] = "1.0"
    second["registration_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in second.items() if key != "registration_hash"}
    )
    payload["registrations"] = [second, payload["registrations"][0]]
    _assert_registry_invalid(tmp_path, _rehash_registry(payload))


def test_skill_artifact_must_match_exact_capability_binding(tmp_path: Path) -> None:
    damaged = deepcopy(_registry_payload())
    damaged["registrations"][0]["skill_artifact"]["skill_id"] = (
        "FINANCE.UNTRUSTED_SKILL"
    )
    path = _write_registry(tmp_path, _rehash_registry(damaged, registration=True))

    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(path)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_INVALID"
    assert "does not match" in str(raised.value)


def test_registration_hash_and_baseline_conflict_fail_closed(tmp_path: Path) -> None:
    damaged = deepcopy(_registry_payload())
    damaged["registrations"][0]["registration_hash"] = "sha256:" + "0" * 64
    path = _write_registry(tmp_path, _rehash_registry(damaged))
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(path)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_INVALID"

    registry = load_product_capability_registry(_environ())
    registration = registry.resolve(GOLDEN_A_CAPABILITY_ID, required=True)
    assert registration is not None
    with pytest.raises(ProductCapabilityRegistryError) as raised:
        registry.merge_capabilities((*DEFAULT_P5_CAPABILITIES, registration.capability))
    assert raised.value.error_code == "PRODUCT_CAPABILITY_BASELINE_CONFLICT"
