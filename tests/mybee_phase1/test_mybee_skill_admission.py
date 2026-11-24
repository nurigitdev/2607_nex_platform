from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from mybee_ax.integrations import nex_tool_bindings as bindings_module
from mybee_ax.integrations.nex_skill_packs import load_skill_pack_manifests
from mybee_ax.integrations.nex_tool_bindings import (
    M1_CHECKPOINT_ID,
    M1_D04_CAPABILITY_ID,
    M1_D04_WORK_CODE_ID,
    M1_D12_CAPABILITY_ID,
    M1_D12_WORK_CODE_ID,
    M1SkillAdmissionError,
    build_pa_nsl_invocation_plan,
    load_m1_signed_skill_release,
    verify_pa_nsl_invocation_plan,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    load_product_capability_registry,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v3.json"
SIGNED_RELEASE_REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
)
CANONICAL_REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
)

TENANT = "VO00"
PROJECT_ID = "019aa111-1111-4111-8111-111111111111"
AGENT_ID = "019aa222-2222-4222-8222-222222222222"
SUBJECT_ID = "019aa333-3333-4333-8333-333333333333"


def _project(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": "VO00D260001",
        "project_state": "ACTIVE",
    }
    value.update(overrides)
    return value


def _agent(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": "VO00D260001",
        "agent_type": "PA",
        "agent_id": AGENT_ID,
        "agent_status": "ACTIVE",
        "capability_mode": "ORDINARY",
    }
    value.update(overrides)
    return value


def _journal(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "nex.eos.journal-post-command.v1",
        "tenant_id": TENANT,
        "company_id": "019aa444-4444-4444-8444-444444444444",
        "candidate_id": "019aa555-5555-4555-8555-555555555555",
        "expected_candidate_version": 3,
        "expected_candidate_revision": 2,
        "expected_candidate_hash": "sha256:" + "a" * 64,
        "accounting_approval_evidence_id": "approval-evidence-001",
    }
    value.update(overrides)
    return value


def _plan(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "release": load_m1_signed_skill_release(),
        "tenant_id": TENANT,
        "requester_subject_id": SUBJECT_ID,
        "project": _project(),
        "project_agent": _agent(),
        "project_work_code_ids": ["FL0012004", M1_D12_WORK_CODE_ID],
        "business_work_code_id": M1_D04_WORK_CODE_ID,
        "journal_arguments": _journal(),
        "effective_on": "2026-11-15",
    }
    values.update(overrides)
    return build_pa_nsl_invocation_plan(**values)


def _write_lock(tmp_path: Path, mutation) -> Path:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))
    mutation(payload)
    payload["content_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    path = tmp_path / "release.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_signed_d04_d12_release_is_source_backed_and_production_verified() -> None:
    release = load_m1_signed_skill_release()

    assert release.checkpoint_id == M1_CHECKPOINT_ID
    assert release.release_id == "nex-mybee-m1-d04-d12-checkpoint-v3"
    assert release.release_version == 3
    assert release.package_hash == (
        "sha256:a2397cc11559d882e11bfaaa4ecf742ab965158b1cbcebb8dc32bf0eaf477b9c"
    )
    assert release.signing_key_id == "release:nex-mybee-m1-checkpoint-2026-11-v3"
    assert {item.capability_id for item in release.skills} == {
        M1_D04_CAPABILITY_ID,
        M1_D12_CAPABILITY_ID,
    }
    assert {
        (item.work_code_id, item.binding_role, item.capability_id)
        for item in release.fl_bindings
    } == {
        (M1_D04_WORK_CODE_ID, "PRIMARY_ACTION", M1_D04_CAPABILITY_ID),
        (M1_D12_WORK_CODE_ID, "PROJECT_CONTEXT", M1_D12_CAPABILITY_ID),
    }
    d04 = release.verified_skill_for_capability(M1_D04_CAPABILITY_ID).skill
    assert d04.skill_version == "1.0.2"
    assert [type(statement).__name__ for statement in d04.body[:4]] == [
        "CheckStatement",
        "CheckStatement",
        "CheckStatement",
        "ApprovalStatement",
    ]


def test_previous_signed_release_remains_verifiable_for_controlled_rollback() -> None:
    previous = load_m1_signed_skill_release(
        ROOT / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json"
    )

    assert previous.release_id == "nex-mybee-m1-d04-d12-checkpoint"
    assert previous.release_version == 1
    assert (
        previous.skill_for_capability(M1_D04_CAPABILITY_ID).skill_version
        == "1.0.0"
    )


def test_canonical_m1_registry_admits_signed_subset_without_retired_golden_a() -> None:
    registry = load_product_capability_registry(
        {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(CANONICAL_REGISTRY)}
    )

    assert registry.registry_id == "ae-product-capabilities-mybee-m1"
    assert registry.registry_version == 6
    assert [item.capability_id for item in registry.registrations] == [
        M1_D04_CAPABILITY_ID,
        M1_D12_CAPABILITY_ID,
    ]
    for capability_id in (M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID):
        registration = registry.resolve(capability_id, required=True)
        assert registration is not None
        assert registration.capability["status"] == "ACTIVE"
        assert (
            registration.capability["local_skill_binding"]["package_requirement"]
            == "SIGNED_TRUSTED_ACTIVE"
        )


def test_candidate_packs_remain_unpromoted_while_compose_selects_m1_release() -> None:
    packs = load_skill_pack_manifests()
    assert len([binding for pack in packs for binding in pack.bindings]) == 18
    assert all(pack.runtime_selectable is False for pack in packs)
    assert all(
        binding.runtime_selectable is False
        for pack in packs
        for binding in pack.bindings
    )

    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    assert (
        "/app/deployment/product/repository/deployment/environments/"
        "ae-product-capability-registry.mybee-m1.v5.json"
    ) in compose
    assert "/app/deployment/product/config/ae-product-capability-registry.v1.json" not in compose


def test_pa_plan_is_deterministic_context_then_governed_write() -> None:
    first = _plan()
    second = _plan(project_work_code_ids=[M1_D12_WORK_CODE_ID, "FL0012004"])

    assert first == second == verify_pa_nsl_invocation_plan(first)
    assert first["checkpoint_id"] == M1_CHECKPOINT_ID
    assert first["principal"] == {
        "tenant_id": TENANT,
        "requester_subject_id": SUBJECT_ID,
        "agent_type": "PA",
        "agent_id": AGENT_ID,
    }
    assert [step["capability_id"] for step in first["steps"]] == [
        M1_D12_CAPABILITY_ID,
        M1_D04_CAPABILITY_ID,
    ]
    assert first["steps"][0]["arguments"]["project_id"] == PROJECT_ID
    assert first["steps"][1]["approval_requirement"] == "ACCOUNTING_POSTING"
    assert first["plan_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in first.items() if key != "plan_hash"}
    )


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    (
        ({"project": _project(project_state="INACTIVE")}, "M1_PROJECT_NOT_ACTIVE"),
        ({"project": _project(tenant_id="OTHER")}, "M1_PROJECT_NOT_ACTIVE"),
        ({"project": _project(project_code="bad code")}, "M1_PROJECT_CODE_INVALID"),
        (
            {"project_agent": _agent(project_id=SUBJECT_ID)},
            "M1_PROJECT_AGENT_SCOPE_MISMATCH",
        ),
        ({"project_agent": _agent(agent_type="IA")}, "M1_AGENT_TYPE_DENIED"),
        (
            {"project_agent": _agent(agent_status="SUSPENDED")},
            "M1_PROJECT_AGENT_INACTIVE",
        ),
        (
            {"project_agent": _agent(capability_mode="CLOSURE")},
            "M1_CAPABILITY_MODE_DENIED",
        ),
        (
            {"project_work_code_ids": ["FL0012004"]},
            "M1_PROJECT_CONTEXT_WORK_CODE_REQUIRED",
        ),
        ({"business_work_code_id": "FL0004008"}, "M1_PRIMARY_WORK_CODE_DENIED"),
        ({"effective_on": "2026-13-40"}, "M1_EFFECTIVE_DATE_INVALID"),
        (
            {"journal_arguments": _journal(tenant_id="OTHER")},
            "M1_JOURNAL_TENANT_MISMATCH",
        ),
        ({"journal_arguments": {"tenant_id": TENANT}}, "M1_JOURNAL_ARGUMENTS_INVALID"),
    ),
)
def test_pa_orchestration_boundary_fails_closed(
    overrides: dict[str, object], error_code: str
) -> None:
    with pytest.raises(M1SkillAdmissionError) as raised:
        _plan(**overrides)
    assert raised.value.code == error_code


def test_pa_plan_requires_admitted_release_and_known_capability() -> None:
    with pytest.raises(M1SkillAdmissionError) as raised:
        _plan(release=object())
    assert raised.value.code == "M1_RELEASE_REQUIRED"

    release = load_m1_signed_skill_release()
    with pytest.raises(M1SkillAdmissionError) as raised:
        release.skill_for_capability("UNKNOWN.CAPABILITY")
    assert raised.value.code == "M1_CAPABILITY_NOT_ADMITTED"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    (
        ({"tenant_id": ""}, "M1_FIELD_INVALID"),
        ({"project": _project(project_id="not-a-uuid")}, "M1_FIELD_INVALID"),
        ({"project_agent": _agent(agent_id="not-a-uuid")}, "M1_FIELD_INVALID"),
        (
            {"journal_arguments": _journal(expected_candidate_version=0)},
            "M1_FIELD_INVALID",
        ),
        (
            {"journal_arguments": _journal(accounting_approval_evidence_id="")},
            "M1_FIELD_INVALID",
        ),
    ),
)
def test_pa_plan_field_validation_is_fail_closed(
    overrides: dict[str, object], error_code: str
) -> None:
    with pytest.raises(M1SkillAdmissionError) as raised:
        _plan(**overrides)
    assert raised.value.code == error_code


@pytest.mark.parametrize(
    "mutation",
    ("hash", "schema", "checkpoint", "agent", "project", "steps"),
)
def test_materialized_pa_plan_tampering_fails_closed(mutation: str) -> None:
    plan = deepcopy(_plan())
    if mutation == "hash":
        plan["plan_hash"] = "sha256:" + "0" * 64
    elif mutation == "schema":
        plan["schema_version"] = "unsupported"
    elif mutation == "checkpoint":
        plan["checkpoint_id"] = "OTHER"
    elif mutation == "agent":
        plan["principal"]["agent_type"] = "IA"
    elif mutation == "project":
        plan["project"]["project_state"] = "INACTIVE"
    else:
        plan["steps"].reverse()
    if mutation != "hash":
        plan["plan_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in plan.items() if key != "plan_hash"}
        )

    with pytest.raises(M1SkillAdmissionError):
        verify_pa_nsl_invocation_plan(plan)


def test_materialized_pa_plan_requires_an_object() -> None:
    with pytest.raises(M1SkillAdmissionError) as raised:
        verify_pa_nsl_invocation_plan([])
    assert raised.value.code == "M1_PA_PLAN_INVALID"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    (
        (
            lambda value: value.update(schema_version="unsupported"),
            "M1_RELEASE_SCHEMA_UNSUPPORTED",
        ),
        (lambda value: value.update(checkpoint_id="OTHER"), "M1_CHECKPOINT_ID_INVALID"),
        (lambda value: value.update(release_state="CANDIDATE"), "M1_RELEASE_INACTIVE"),
        (
            lambda value: value.update(runtime_selectable=False),
            "M1_RELEASE_NOT_SELECTABLE",
        ),
        (
            lambda value: value["nsl_runtime"].update(package_version="0.3.0"),
            "M1_NSL_VERSION_INVALID",
        ),
        (lambda value: value.update(skills=[]), "M1_SKILL_SET_INVALID"),
        (
            lambda value: value["skills"][0].update(capability_id="UNKNOWN"),
            "M1_SKILL_SET_INVALID",
        ),
        (
            lambda value: value["skills"][0].update(semantic_hash="sha256:" + "0" * 64),
            "M1_SKILL_IDENTITY_MISMATCH",
        ),
        (lambda value: value.update(fl_bindings=[]), "M1_FL_BINDINGS_INVALID"),
        (
            lambda value: value["fl_bindings"][0].update(work_code_id="FL0004008"),
            "M1_FL_BINDINGS_INVALID",
        ),
        (
            lambda value: value["product_capability_registry"].update(
                registry_id="wrong"
            ),
            "M1_REGISTRY_IDENTITY_MISMATCH",
        ),
        (
            lambda value: value["package"].update(package_hash="sha256:" + "1" * 64),
            "M1_NSP_PACKAGE_HASH_MISMATCH",
        ),
    ),
)
def test_release_semantic_mutations_fail_closed(
    tmp_path: Path, mutation, error_code: str
) -> None:
    path = _write_lock(tmp_path, mutation)

    with pytest.raises(M1SkillAdmissionError) as raised:
        load_m1_signed_skill_release(path, repository_root=ROOT)
    assert raised.value.code == error_code


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    (
        ("wheel_lock_ref", "../outside.json", "M1_ARTIFACT_UNAVAILABLE"),
        ("wheel_lock_sha256", "sha256:" + "0" * 64, "M1_ARTIFACT_HASH_MISMATCH"),
    ),
)
def test_release_artifact_reference_failures_are_distinct(
    tmp_path: Path, field: str, value: str, error_code: str
) -> None:
    def mutate(payload: dict) -> None:
        payload["nsl_runtime"][field] = value

    path = _write_lock(tmp_path, mutate)
    with pytest.raises(M1SkillAdmissionError) as raised:
        load_m1_signed_skill_release(path, repository_root=ROOT)
    assert raised.value.code == error_code


def test_signature_verifier_failure_is_normalized(monkeypatch, tmp_path: Path) -> None:
    class BrokenVerifier:
        def __init__(self, **_kwargs) -> None:
            pass

        def verify(self, _payload: bytes) -> object:
            raise ValueError("invalid signature")

    monkeypatch.setattr(bindings_module, "NspVerifier", BrokenVerifier)
    with pytest.raises(M1SkillAdmissionError) as raised:
        load_m1_signed_skill_release()
    assert raised.value.code == "M1_NSP_SIGNATURE_INVALID"


def test_candidate_binding_missing_and_drift_are_rejected(monkeypatch) -> None:
    release = load_m1_signed_skill_release()
    monkeypatch.setattr(
        bindings_module, "load_skill_pack_manifests", lambda *_args, **_kwargs: ()
    )
    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._verify_candidate_bindings(release.skills, repository_root=ROOT)
    assert raised.value.code == "M1_CANDIDATE_BINDING_MISSING"

    real = load_skill_pack_manifests()
    candidate = next(
        binding
        for pack in real
        for binding in pack.bindings
        if binding.canonical_operation_id == M1_D04_CAPABILITY_ID
    )
    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._verify_candidate_binding(
            release.skill_for_capability(M1_D04_CAPABILITY_ID),
            replace(candidate, runtime_selectable=True),
        )
    assert raised.value.code == "M1_CANDIDATE_BINDING_DRIFT"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    (
        (
            lambda value: value.update(registry_hash="sha256:" + "0" * 64),
            "M1_REGISTRY_HASH_MISMATCH",
        ),
        (lambda value: value.update(registrations={}), "M1_REGISTRY_INVALID"),
        (
            lambda value: value.update(registrations=[]),
            "M1_REGISTRY_CAPABILITY_MISSING",
        ),
        (
            lambda value: value["registrations"][1]["capability"].update(
                status="CANDIDATE"
            ),
            "M1_REGISTRY_CAPABILITY_DRIFT",
        ),
    ),
)
def test_registry_internal_drift_is_rejected(mutation, error_code: str) -> None:
    release = load_m1_signed_skill_release()
    registry = json.loads(SIGNED_RELEASE_REGISTRY.read_text(encoding="utf-8"))
    reference = json.loads(LOCK.read_text(encoding="utf-8"))[
        "product_capability_registry"
    ]
    mutation(registry)
    if error_code == "M1_REGISTRY_HASH_MISMATCH":
        reference = dict(reference, registry_hash=registry["registry_hash"])
    else:
        registry["registry_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in registry.items() if key != "registry_hash"}
        )
        reference = dict(reference, registry_hash=registry["registry_hash"])

    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._verify_registry(registry, reference, release.skills)
    assert raised.value.code == error_code


def test_trust_key_and_json_helpers_reject_malformed_inputs(tmp_path: Path) -> None:
    package = json.loads(LOCK.read_text(encoding="utf-8"))["package"]
    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._require_exact_key({}, package)
    assert raised.value.code == "M1_TRUST_KEY_INVALID"

    bad_key = {
        "schema_version": "nex.mybee.nsp-trust-key.v1",
        "algorithm": "RSA",
        "key_id": package["signing_key_id"],
        "public_key_base64": "AA",
        "usage": "VERIFY_ONLY",
        "private_key_persisted": False,
    }
    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._require_exact_key(bad_key, package)
    assert raised.value.code == "M1_TRUST_KEY_INVALID"

    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._decode_public_key("AA")
    assert raised.value.code == "M1_TRUST_KEY_INVALID"

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("not-json", encoding="utf-8")
    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._json(invalid_json, "INVALID_JSON")
    assert raised.value.code == "INVALID_JSON"

    array_json = tmp_path / "array.json"
    array_json.write_text("[]", encoding="utf-8")
    with pytest.raises(M1SkillAdmissionError) as raised:
        bindings_module._json(array_json, "INVALID_JSON")
    assert raised.value.code == "M1_FIELD_INVALID"


def test_release_lock_semantic_drift_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))
    payload["activation_boundary"]["allowed_agent_types"] = ["IA", "PA"]
    payload["content_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    path = tmp_path / "release.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(M1SkillAdmissionError) as raised:
        load_m1_signed_skill_release(path, repository_root=ROOT)
    assert raised.value.code == "M1_ACTIVATION_BOUNDARY_DRIFT"


def test_release_lock_hash_drift_fails_before_artifact_admission(
    tmp_path: Path,
) -> None:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))
    payload["release_version"] = 4
    path = tmp_path / "release.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(M1SkillAdmissionError) as raised:
        load_m1_signed_skill_release(path, repository_root=ROOT)
    assert raised.value.code == "M1_RELEASE_HASH_MISMATCH"


def test_mybee_binding_module_respects_service_ownership_boundaries() -> None:
    source = (
        ROOT / "domains/mybee/mybee_ax/integrations/nex_tool_bindings.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "import nex_eos",
        "from nex_eos",
        "import nex_ae_api",
        "from nex_ae_api",
        "sqlalchemy",
        "requests.",
        "httpx.",
    ):
        assert forbidden not in source
