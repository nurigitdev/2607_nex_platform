from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from build_mybee_w70_golden_a_retirement import (
    INVENTORY_PATH,
    PROJECTION_PATH,
    ROLLBACK_PATH,
    build_retirement_artifacts,
    render_json,
)
from nex_ae_api.domain_intent_products import (
    build_domain_intent_activator_registry,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    ProductCapabilityRegistry,
    load_product_capability_registry,
)
from nex_ae_api.product_capability_retirements import (
    PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV,
    ProductCapabilityRetirementError,
    ProductCapabilityRetirementProjection,
    _validate_projection,
    load_product_capability_retirement_projection,
)
from nex_ae_api.semantic_candidate_admission import (
    DeterministicCandidateAdmissionService,
    SemanticCandidateAdmissionError,
    SemanticCandidateAdmissionRequest,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_mybee_w70_golden_a_retirement_gate import run_gate
from run_mybee_w70_golden_a_retirement_postgres import (
    DATABASE_ENV,
    SMOKE_ENV,
    _lineage_cte,
    run_postgres_smoke,
)

ROOT = Path(__file__).resolve().parents[2]
V1_REGISTRY = ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
M1_REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json"
)
AUTHORITY = ROOT / "deployment/environments/finance-golden-a-vo00.v1.json"
GOLDEN_A = "FINANCE.CREATE_VOUCHER_DRAFT"


def _projection():
    return load_product_capability_retirement_projection(
        {PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV: str(ROOT / PROJECTION_PATH)},
        required=True,
    )


def _registry(path: Path):
    return load_product_capability_registry(
        {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(path)}
    )


def _product_environ() -> dict[str, str]:
    return {
        "NEX_DEPLOYMENT_BOUNDARY": "CANONICAL_PLATFORM",
        PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(V1_REGISTRY),
        PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV: str(ROOT / PROJECTION_PATH),
        "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH": str(AUTHORITY),
    }


def test_retirement_artifacts_are_exact_and_gate_passes() -> None:
    artifacts = build_retirement_artifacts(ROOT)

    assert set(artifacts) == {INVENTORY_PATH, ROLLBACK_PATH, PROJECTION_PATH}
    for relative, value in artifacts.items():
        assert (ROOT / relative).read_bytes() == render_json(value)
    result = run_gate(ROOT)
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["reference_count"] >= 190


def test_projection_removes_golden_a_but_keeps_signed_m1_capabilities() -> None:
    projection = _projection()
    v1 = projection.selectable_registry(_registry(V1_REGISTRY))
    m1 = projection.selectable_registry(_registry(M1_REGISTRY))
    empty = ProductCapabilityRegistry(
        (), registry_id="empty-registry", registry_version=1
    )

    assert v1.registrations == ()
    assert {item.capability_id for item in m1.registrations} == {
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "PROJECT.WORK_CODE_SET.GET",
    }
    assert projection.retirement_for("createEosVoucherDraft") is not None
    assert projection.retirement_for("PROJECT.WORK_CODE_SET.GET") is None
    assert projection.retirement_for(None) is None
    assert projection.is_new_selection_denied(None) is False
    assert projection.selectable_registry(empty) is empty


def test_public_activator_is_removed_while_explicit_replay_remains() -> None:
    public = build_domain_intent_activator_registry(_product_environ())
    replay = build_domain_intent_activator_registry(
        _product_environ(), include_replay_only=True
    )

    assert public.resolve(GOLDEN_A) is None
    assert replay.resolve(GOLDEN_A, required=True) is not None


def test_public_activator_without_authority_is_empty() -> None:
    assert build_domain_intent_activator_registry({}).registrations == ()


def test_canonical_activator_requires_retirement_projection() -> None:
    environ = _product_environ()
    environ.pop(PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV)

    with pytest.raises(ProductCapabilityRetirementError) as raised:
        build_domain_intent_activator_registry(environ)
    assert raised.value.error_code == "PRODUCT_CAPABILITY_RETIREMENT_REQUIRED"


def test_optional_empty_projection_and_uncovered_registry_fail_closed() -> None:
    assert load_product_capability_retirement_projection({}) == (
        ProductCapabilityRetirementProjection()
    )
    with pytest.raises(ProductCapabilityRetirementError) as raised:
        load_product_capability_retirement_projection({}, required=True)
    assert raised.value.error_code == "PRODUCT_CAPABILITY_RETIREMENT_REQUIRED"

    source = _registry(V1_REGISTRY)
    registration = source.registrations[0]
    uncovered = ProductCapabilityRegistry(
        (registration,), registry_id="uncovered", registry_version=9
    )
    with pytest.raises(ProductCapabilityRetirementError) as raised:
        _projection().selectable_registry(uncovered)
    assert raised.value.error_code == (
        "PRODUCT_CAPABILITY_RETIREMENT_REGISTRY_UNCOVERED"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "non_object",
        "fields",
        "schema",
        "projection_hash",
        "covered_order",
        "covered_duplicate",
        "aliases_order",
        "state",
        "selection",
        "in_flight",
        "asset_policy",
        "retirement_hash",
        "artifact_ref",
        "covered_empty",
        "covered_fields",
        "covered_version_bool",
        "covered_hash",
        "retirements_empty",
        "retirement_fields",
        "retirement_order",
        "retirement_overlap",
        "aliases_empty",
        "aliases_non_text",
        "aliases_duplicate",
        "capability_version_blank",
        "reason_too_long",
        "projection_version_zero",
        "projection_id_whitespace",
    ),
)
def test_retirement_projection_drift_is_rejected(
    tmp_path: Path, mutation: str
) -> None:
    payload: object = json.loads((ROOT / PROJECTION_PATH).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    if mutation == "non_object":
        payload = []
    elif mutation == "fields":
        payload["unexpected"] = True
    elif mutation == "schema":
        payload["schema_version"] = "unsupported"
    elif mutation == "projection_hash":
        payload["projection_hash"] = "sha256:" + "0" * 64
    elif mutation == "covered_order":
        payload["covered_registries"] = list(
            reversed(payload["covered_registries"])
        )
    elif mutation == "covered_duplicate":
        payload["covered_registries"].append(
            deepcopy(payload["covered_registries"][0])
        )
    elif mutation == "aliases_order":
        payload["retirements"][0]["compatibility_aliases"] = list(
            reversed(payload["retirements"][0]["compatibility_aliases"])
        )
        _rehash_retirement(payload)
    elif mutation == "state":
        payload["retirements"][0]["retirement_state"] = "ACTIVE"
        _rehash_retirement(payload)
    elif mutation == "selection":
        payload["retirements"][0]["new_selection"] = "ALLOW"
        _rehash_retirement(payload)
    elif mutation == "in_flight":
        payload["retirements"][0]["in_flight_policy"] = "DROP"
        _rehash_retirement(payload)
    elif mutation == "asset_policy":
        payload["retirements"][0]["active_asset_policy"] = "DELETE"
        _rehash_retirement(payload)
    elif mutation == "retirement_hash":
        payload["retirements"][0]["retirement_hash"] = "sha256:" + "1" * 64
    elif mutation == "artifact_ref":
        payload["inventory_ref"] = {"path": "missing"}
    elif mutation == "covered_empty":
        payload["covered_registries"] = []
    elif mutation == "covered_fields":
        payload["covered_registries"][0]["unexpected"] = True
    elif mutation == "covered_version_bool":
        payload["covered_registries"][0]["registry_version"] = True
    elif mutation == "covered_hash":
        payload["covered_registries"][0]["registry_hash"] = "invalid"
    elif mutation == "retirements_empty":
        payload["retirements"] = []
    elif mutation == "retirement_fields":
        payload["retirements"][0]["unexpected"] = True
    elif mutation in {"retirement_order", "retirement_overlap"}:
        duplicate = deepcopy(payload["retirements"][0])
        duplicate["capability_id"] = (
            "AAA.RETIRED" if mutation == "retirement_order" else "ZZZ.RETIRED"
        )
        duplicate["retirement_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in duplicate.items()
                if key != "retirement_hash"
            }
        )
        payload["retirements"].append(duplicate)
    elif mutation == "aliases_empty":
        payload["retirements"][0]["compatibility_aliases"] = []
        _rehash_retirement(payload)
    elif mutation == "aliases_non_text":
        payload["retirements"][0]["compatibility_aliases"] = [1]
        _rehash_retirement(payload)
    elif mutation == "aliases_duplicate":
        alias = payload["retirements"][0]["compatibility_aliases"][0]
        payload["retirements"][0]["compatibility_aliases"] = [alias, alias]
        _rehash_retirement(payload)
    elif mutation == "capability_version_blank":
        payload["retirements"][0]["capability_version"] = " "
        _rehash_retirement(payload)
    elif mutation == "reason_too_long":
        payload["retirements"][0]["reason_code"] = "x" * 161
        _rehash_retirement(payload)
    elif mutation == "projection_version_zero":
        payload["projection_version"] = 0
    elif mutation == "projection_id_whitespace":
        payload["projection_id"] = " invalid"
    if isinstance(payload, dict) and mutation != "projection_hash":
        payload["projection_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in payload.items() if key != "projection_hash"}
        )
    path = tmp_path / "projection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProductCapabilityRetirementError):
        load_product_capability_retirement_projection(
            {PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV: str(path)}, required=True
        )


def test_retirement_projection_unavailable_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ProductCapabilityRetirementError) as raised:
        load_product_capability_retirement_projection(
            {
                PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV: str(
                    tmp_path / "missing.json"
                )
            },
            required=True,
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_RETIREMENT_UNAVAILABLE"


def test_projection_rejects_non_canonical_python_value() -> None:
    with pytest.raises(ProductCapabilityRetirementError) as raised:
        _validate_projection({"unsupported": {object()}})
    assert str(raised.value) == (
        "Product capability retirement projection must be canonical JSON."
    )


def test_new_intent_candidate_is_blocked_before_private_storage() -> None:
    evidence = _EvidenceStore(None)
    storage = _CandidateStorage(None)
    service = _service(evidence=evidence, storage=storage)

    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        service._stage(
            request=_request(),
            execution_id="30000000-0000-4000-8000-000000000001",
            semantic_stage="INTENT",
            candidate_id="30000000-0000-4000-8000-000000000002",
            invoke=lambda: _intent_result(GOLDEN_A),
            now="2026-11-15T00:00:00Z",
        )

    assert raised.value.error_code == "CANDIDATE_CAPABILITY_RETIRED"
    assert storage.saved == []
    assert evidence.saved == []


def test_existing_intent_candidate_replay_remains_available_for_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = {
        "tenant_id": "VO00",
        "owner_subject_id": "employee-1001",
        "execution_id": "30000000-0000-4000-8000-000000000001",
        "semantic_stage": "INTENT",
        "candidate_revision": 1,
        "candidate_id": "30000000-0000-4000-8000-000000000002",
        "storage_ref": "private://candidate/retired",
        "content_sha256": "0" * 64,
        "content_size": 1,
    }
    candidate = {"intent_label": GOLDEN_A}
    monkeypatch.setattr(
        "nex_ae_api.semantic_candidate_admission."
        "candidate_payload_metadata_from_evidence",
        lambda _evidence: {
            "candidate_id": existing["candidate_id"],
            "content_sha256": "0" * 64,
            "size_bytes": 1,
            "storage_ref": existing["storage_ref"],
        },
    )
    service = _service(
        evidence=_EvidenceStore(existing), storage=_CandidateStorage(candidate)
    )

    observed, loaded, result, resumed = service._stage(
        request=_request(),
        execution_id=existing["execution_id"],
        semantic_stage="INTENT",
        candidate_id=existing["candidate_id"],
        invoke=lambda: (_ for _ in ()).throw(AssertionError("must replay")),
        now="2026-11-15T00:00:00Z",
    )

    assert observed is existing
    assert loaded == candidate
    assert result is None
    assert resumed is True


def test_postgres_runner_is_opt_in_and_query_covers_all_lineage_tables() -> None:
    skipped = run_postgres_smoke({})
    rejected = run_postgres_smoke(
        {
            SMOKE_ENV: "1",
            DATABASE_ENV: "postgresql://wrong@127.0.0.1/other",
        }
    )
    query = _lineage_cte()

    assert skipped["status"] == "SKIPPED"
    assert rejected["failure_code"] == "target_not_allowed"
    assert all(
        table in query
        for table in ("ae_work_intent", "ae_agent_plan", "ae_executable_plan")
    )
    assert "FINANCE.CREATE_VOUCHER_DRAFT" in query


def _rehash_retirement(payload: dict) -> None:
    retirement = payload["retirements"][0]
    retirement["retirement_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in retirement.items()
            if key != "retirement_hash"
        }
    )


class _EvidenceStore:
    def __init__(self, existing):
        self.existing = existing
        self.saved = []

    def get(self, **_kwargs):
        return self.existing

    def save(self, value):
        self.saved.append(value)
        return value


class _CandidateStorage:
    def __init__(self, existing):
        self.existing = existing
        self.saved = []

    def load(self, *_args, **_kwargs):
        return self.existing

    def save(self, value, **_kwargs):
        self.saved.append(value)
        return value["storage_ref"]


def _service(*, evidence, storage) -> DeterministicCandidateAdmissionService:
    return DeterministicCandidateAdmissionService(
        mode="required",
        admission=SimpleNamespace(),
        intent_stage=SimpleNamespace(),
        context_stage=SimpleNamespace(),
        plan_stage=SimpleNamespace(),
        evidence=evidence,
        candidate_storage=storage,
        work_intents=SimpleNamespace(),
        contexts=SimpleNamespace(),
        capabilities=SimpleNamespace(),
        plans=SimpleNamespace(),
        validations=SimpleNamespace(),
        executable_plans=SimpleNamespace(),
        executions=SimpleNamespace(),
        product_capability_retirements=_projection(),
    )


def _request() -> SemanticCandidateAdmissionRequest:
    return SemanticCandidateAdmissionRequest(
        tenant_id="VO00",
        owner_subject_id="employee-1001",
        profile_ref="urn:nex:agent-profile:ia:default:v1",
        interaction_id="30000000-0000-4000-8000-000000000003",
        workspace_id="30000000-0000-4000-8000-000000000004",
        conversation_id="30000000-0000-4000-8000-000000000005",
        correlation_id="retirement-test",
        request_id="retirement-test",
        trace_id="0" * 32,
        user_prompt="retired request",
        base_context={},
        runtime_policy_ref={},
        context_resolver=SimpleNamespace(),
        capability_snapshot={},
    )


def _intent_result(intent_label: str):
    return SimpleNamespace(
        candidate={"intent_label": intent_label},
        admission_policy_ref="policy://nex/test/retirement/v1",
    )
