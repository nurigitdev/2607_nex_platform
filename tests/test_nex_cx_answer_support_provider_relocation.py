from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from nex_cx.retrieval_answer_support_controlled_activation import (
    load_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_provider_relocation import (
    AnswerSupportProviderRelocationError,
    RELOCATION_PATH_ENV,
    load_provider_relocation,
    resolve_runtime_provider_binding,
    validate_provider_relocation,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    _runtime_provider_binding,
)
from nex_runtime.canonical_generation_binding import CANONICAL_GENERATION_BINDING
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


ROOT = Path(__file__).resolve().parents[1]
ACTIVATION_PATH = (
    ROOT
    / "services/nex-cx/nex_cx/data/answer_support_controlled_activation.v1.json"
)
RELOCATION_PATH = (
    ROOT
    / "services/nex-cx/nex_cx/data/answer_support_provider_relocation.v1.json"
)


def test_relocation_preserves_calibration_and_admits_canonical_deployment() -> None:
    activation = load_controlled_activation_bundle(ACTIVATION_PATH)
    relocation = load_provider_relocation(
        RELOCATION_PATH,
        activation_bundle=activation,
    )
    source = relocation["source_provider_binding"]
    target = relocation["target_provider_binding"]

    assert source["deployment_id"] == "dgx-qwen3-5-9b-9116"
    assert target["deployment_id"] == CANONICAL_GENERATION_BINDING.deployment_id
    assert target["model_revision"] == source["model_revision"]
    assert target["request_profile_id"] == source["request_profile_id"]
    assert target["score_semantics_id"] == source["score_semantics_id"]
    assert resolve_runtime_provider_binding(
        {RELOCATION_PATH_ENV: str(RELOCATION_PATH)},
        activation_bundle=activation,
    ) == target
    assert resolve_runtime_provider_binding({}, activation_bundle=activation) is None


def test_relocation_fails_closed_for_tamper_and_semantic_change() -> None:
    activation = load_controlled_activation_bundle(ACTIVATION_PATH)
    relocation = load_provider_relocation(
        RELOCATION_PATH,
        activation_bundle=activation,
    )
    tampered = deepcopy(relocation)
    tampered["target_provider_binding"]["deployment_id"] = "tampered"
    with pytest.raises(AnswerSupportProviderRelocationError, match="hash"):
        validate_provider_relocation(tampered, activation_bundle=activation)

    semantic_change = deepcopy(relocation)
    semantic_change.pop("amendment_hash")
    semantic_change["target_provider_binding"]["model_revision"] = "hf:" + "1" * 40
    semantic_change["amendment_hash"] = semantic_sha256_hash_ref(semantic_change)
    with pytest.raises(AnswerSupportProviderRelocationError, match="semantics"):
        validate_provider_relocation(semantic_change, activation_bundle=activation)


def test_runtime_binding_override_only_allows_deployment_relocation() -> None:
    activation = load_controlled_activation_bundle(ACTIVATION_PATH)
    calibrated = activation["readiness_manifest"]["candidate_profile"][
        "provider_binding"
    ]
    target = load_provider_relocation(
        RELOCATION_PATH,
        activation_bundle=activation,
    )["target_provider_binding"]

    assert _runtime_provider_binding(calibrated, None) == calibrated
    assert _runtime_provider_binding(calibrated, target) == target
    invalid = dict(target, request_profile_id="changed")
    with pytest.raises(ValueError, match="calibrated semantics"):
        _runtime_provider_binding(calibrated, invalid)
    with pytest.raises(ValueError, match="fields"):
        _runtime_provider_binding(calibrated, {"deployment_id": "replacement"})
    with pytest.raises(ValueError, match="deployment_id"):
        _runtime_provider_binding(calibrated, dict(target, deployment_id=""))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("relocation_schema_version", "drift"),
        ("status", "PENDING"),
        ("scope", "MODEL_REPLACEMENT"),
        ("operator_decision", "DENIED"),
        ("model_artifact_changed", True),
        ("request_profile_changed", True),
        ("calibration_reuse_authorized", False),
    ),
)
def test_relocation_requires_every_approval_guard(field: str, value: object) -> None:
    activation, relocation = _activation_and_relocation()
    relocation[field] = value
    _rehash(relocation)

    with pytest.raises(AnswerSupportProviderRelocationError, match="not approved"):
        validate_provider_relocation(relocation, activation_bundle=activation)


def test_relocation_rejects_bundle_source_and_target_identity_drift() -> None:
    activation, relocation = _activation_and_relocation()
    relocation["source_activation_bundle_hash"] = "sha256:" + "1" * 64
    _rehash(relocation)
    with pytest.raises(AnswerSupportProviderRelocationError, match="active calibration"):
        validate_provider_relocation(relocation, activation_bundle=activation)

    activation, relocation = _activation_and_relocation()
    relocation["source_provider_binding"]["deployment_id"] = "source-drift"
    _rehash(relocation)
    with pytest.raises(AnswerSupportProviderRelocationError, match="calibrated"):
        validate_provider_relocation(relocation, activation_bundle=activation)

    activation, relocation = _activation_and_relocation()
    relocation["target_provider_binding"]["deployment_id"] = relocation[
        "source_provider_binding"
    ]["deployment_id"]
    _rehash(relocation)
    with pytest.raises(AnswerSupportProviderRelocationError, match="must change"):
        validate_provider_relocation(relocation, activation_bundle=activation)

    activation, relocation = _activation_and_relocation()
    relocation["target_provider_binding"]["deployment_id"] = "noncanonical"
    _rehash(relocation)
    with pytest.raises(AnswerSupportProviderRelocationError, match="not the canonical"):
        validate_provider_relocation(relocation, activation_bundle=activation)


def test_relocation_rejects_malformed_documents_and_unavailable_file(
    tmp_path: Path,
) -> None:
    activation, relocation = _activation_and_relocation()
    relocation.pop("scope")
    with pytest.raises(AnswerSupportProviderRelocationError, match="fields"):
        validate_provider_relocation(relocation, activation_bundle=activation)

    activation, relocation = _activation_and_relocation()
    relocation["target_provider_binding"]["deployment_id"] = ""
    _rehash(relocation)
    with pytest.raises(AnswerSupportProviderRelocationError, match="required"):
        validate_provider_relocation(relocation, activation_bundle=activation)

    with pytest.raises(AnswerSupportProviderRelocationError, match="must be an object"):
        validate_provider_relocation([], activation_bundle=activation)

    activation, relocation = _activation_and_relocation()
    relocation["amendment_hash"] = "invalid"
    with pytest.raises(AnswerSupportProviderRelocationError, match="invalid"):
        validate_provider_relocation(relocation, activation_bundle=activation)

    missing = tmp_path / "missing.json"
    with pytest.raises(AnswerSupportProviderRelocationError, match="unavailable"):
        load_provider_relocation(missing, activation_bundle=activation)
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(AnswerSupportProviderRelocationError, match="unavailable"):
        load_provider_relocation(invalid_json, activation_bundle=activation)


def _activation_and_relocation() -> tuple[dict, dict]:
    activation = load_controlled_activation_bundle(ACTIVATION_PATH)
    relocation = json.loads(RELOCATION_PATH.read_text(encoding="utf-8"))
    return activation, relocation


def _rehash(relocation: dict) -> None:
    relocation.pop("amendment_hash", None)
    relocation["amendment_hash"] = semantic_sha256_hash_ref(relocation)
