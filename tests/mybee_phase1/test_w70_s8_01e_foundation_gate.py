from __future__ import annotations

import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from mybee_ax.integrations import nex_skill_foundation_gate as gate_module
from mybee_ax.integrations.nex_skill_foundation_gate import (
    W70FoundationGateError,
    build_w70_foundation_gate_receipt,
    render_foundation_gate_json,
    verify_w70_foundation_gate_receipt,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    ProductCapabilityRegistryError,
    load_product_capability_registry,
)
from nex_runtime.operation_names import (
    CanonicalOperationRegistry,
    OperationNameError,
)

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "reports/quality/mybee-w70-s8-01-foundation-gate.json"
REGISTRY_V2 = ROOT / "deployment/environments/ae-product-capability-registry.v2.json"

STATUS_ONLY = {
    "FINANCE.COST_ALLOCATION_PLAN.RELEASE",
    "FINANCE.FX_RATE.HISTORY",
    "FINANCE.FX_RATE.IMPORT",
    "FINANCE.FX_RATE.RESOLVE",
    "FINANCE.VOUCHER_CANDIDATE.GET_V2",
    "PROJECT.WORK_ASSIGNMENT.ASSIGN",
    "PROJECT.WORK_CODE_SET.APPROVE",
}


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_checked_in_foundation_gate_receipt_is_exact_and_deterministic() -> None:
    first = build_w70_foundation_gate_receipt(ROOT)
    second = build_w70_foundation_gate_receipt(ROOT)

    assert first == second == verify_w70_foundation_gate_receipt(
        RECEIPT, root=ROOT
    )
    assert RECEIPT.read_bytes() == render_foundation_gate_json(first)
    assert first["gate_state"] == "PASS"
    assert first["content_hash"].startswith("sha256:")


def test_compile_profiles_are_deterministic_non_product_evidence() -> None:
    receipt = _json(RECEIPT)
    profiles = receipt["compile_profiles"]

    assert {
        (item["domain_code"], item["operation_semantics"])
        for item in profiles
    } == {
        ("D04_ACCOUNTING", "READ"),
        ("D04_ACCOUNTING", "GOVERNED_WRITE"),
        ("D12_PROJECT", "READ"),
    }
    assert all(item["product_skill"] is False for item in profiles)
    assert all(
        item["admission_state"] == "PROFILE_COMPILE_ADMITTED"
        for item in profiles
    )
    assert all(item["semantic_hash"].startswith("sha256:") for item in profiles)
    assert all(item["nso_sha256"].startswith("sha256:") for item in profiles)


def test_status_only_and_unsigned_candidates_remain_fail_closed() -> None:
    receipt = _json(RECEIPT)
    summary = receipt["candidate_admission"]
    admissions = summary["admissions"]

    assert (summary["total"], summary["fully_typed"], summary["status_only"]) == (
        18,
        11,
        7,
    )
    assert summary["runtime_selectable"] == 0
    assert {
        item["capability_id"]
        for item in admissions
        if item["contract_typing_state"] == "STATUS_ONLY"
    } == STATUS_ONLY
    assert all(item["runtime_selectable"] is False for item in admissions)
    assert all(
        item["compile_admission_state"] == "BLOCKED_STATUS_ONLY_CONTRACT"
        and item["activation_blocker"]
        == "CANONICAL_SUCCESS_RESPONSE_SCHEMA_REQUIRED"
        for item in admissions
        if item["capability_id"] in STATUS_ONLY
    )
    assert all(
        item["signature_status"] == "NOT_SIGNED"
        and item["runtime_selectable"] is False
        and item["admission_state"] == "BLOCKED_UNSIGNED"
        for item in receipt["trust_admission"]["candidate_bundles"]
    )


def test_negative_compile_and_runtime_activation_boundaries_are_explicit() -> None:
    receipt = _json(RECEIPT)

    assert receipt["negative_compile_cases"] == [
        {
            "case_id": "STATUS_ONLY_TOOL_NOT_IN_ADMITTED_COMPILER_CATALOG",
            "source_ref": (
                "domains/mybee/skills/foundation_gate/status_only_negative.ns"
            ),
            "source_sha256": receipt["negative_compile_cases"][0][
                "source_sha256"
            ],
            "expected_error_code": "NSL-E4001",
            "observed_error_code": "NSL-E4001",
            "outcome": "REJECTED_AS_EXPECTED",
        }
    ]
    assert receipt["activation_decision"] == {
        "foundation_gate": "PASS",
        "candidate_product_skills": "NOT_ACTIVATED",
        "signed_minimal_skill_owner": "CP-M1-MB8-01",
        "remote_provider_required": False,
    }

    with pytest.raises(ProductCapabilityRegistryError) as raised:
        load_product_capability_registry(
            {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(REGISTRY_V2)}
        )
    assert raised.value.error_code == "PRODUCT_CAPABILITY_REGISTRY_INVALID"


def test_alias_receipt_is_one_way_and_collision_construction_fails() -> None:
    receipt = _json(RECEIPT)
    aliases = receipt["alias_admission"]["aliases"]

    assert [(item["requested_operation"], item["canonical_operation"]) for item in aliases] == [
        ("FINANCE.CREATE_VOUCHER_DRAFT", "FINANCE.VOUCHER_DRAFT.CREATE"),
        (
            "FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION",
            "FINANCE.VOUCHER_POSTING.ADMIT",
        ),
        ("createEosVoucherDraft", "FINANCE.VOUCHER_DRAFT.CREATE"),
    ]
    assert all(item["alias_applied"] is True for item in aliases)

    with pytest.raises(OperationNameError):
        CanonicalOperationRegistry(
            canonical_operations={"DOMAIN.OBJECT.ACTION"},
            aliases={"DOMAIN.OBJECT.ACTION": "DOMAIN.OBJECT.ACTION"},
        )
    with pytest.raises(OperationNameError):
        CanonicalOperationRegistry(
            canonical_operations={"DOMAIN.OBJECT.ACTION"},
            aliases={"legacyAction": "DOMAIN.OBJECT.UNKNOWN"},
        )


def test_golden_a_receipt_is_historical_while_m1_selection_is_active() -> None:
    receipt = _json(RECEIPT)
    continuity = receipt["registry_continuity"]

    assert continuity["candidate_registry_version"] == 2
    assert continuity["golden_a_runtime_unchanged"] is True
    assert continuity["bundle_set_readiness"]["status"] == "PASS"
    assert continuity["bundle_set_readiness"]["active_bundle_count"] == 1
    assert continuity["bundle_set_readiness"]["candidate_bundle_count"] == 2

    compose = (
        ROOT / "deployment/compose/canonical-platform.override.yaml"
    ).read_text(encoding="utf-8")
    assert "NEX_AE_PRODUCT_RUNTIME_PROFILE: VERIFIED_PRODUCT_RELEASE" in compose
    assert "ae-product-capability-registry.mybee-m1.v1.json" in compose
    assert "/app/deployment/product/config/ae-product-capability-registry.v1.json" not in compose
    assert "ae-product-capability-registry.v2.json" not in compose
    assert "NEX_AE_PRODUCT_CAPABILITY_RETIREMENT_PATH" in compose
    assert "golden-a-selection-freeze.v1.json" in compose


@pytest.mark.parametrize(
    "mutation",
    (
        "gate_state",
        "semantic_hash",
        "candidate_selectable",
        "signature_status",
        "alias_target",
        "active_continuity",
        "content_hash",
    ),
)
def test_receipt_drift_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    payload = deepcopy(_json(RECEIPT))
    if mutation == "gate_state":
        payload["gate_state"] = "FAIL"
    elif mutation == "semantic_hash":
        payload["compile_profiles"][0]["semantic_hash"] = "sha256:" + "0" * 64
    elif mutation == "candidate_selectable":
        payload["candidate_admission"]["admissions"][0][
            "runtime_selectable"
        ] = True
    elif mutation == "signature_status":
        payload["trust_admission"]["candidate_bundles"][0][
            "signature_status"
        ] = "SIGNED"
    elif mutation == "alias_target":
        payload["alias_admission"]["aliases"][0][
            "canonical_operation"
        ] = "FINANCE.PROJECT_PNL.GET"
    elif mutation == "active_continuity":
        payload["registry_continuity"]["golden_a_runtime_unchanged"] = False
    elif mutation == "content_hash":
        payload["content_hash"] = "sha256:" + "1" * 64

    path = tmp_path / "receipt.json"
    path.write_bytes(render_foundation_gate_json(payload))
    with pytest.raises(W70FoundationGateError, match="receipt drift"):
        verify_w70_foundation_gate_receipt(path, root=ROOT)


@pytest.mark.parametrize("payload", ("[]\n", "not-json\n"))
def test_receipt_non_object_and_invalid_json_fail_closed(
    tmp_path: Path, payload: str
) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(W70FoundationGateError, match="unreadable JSON|expected JSON"):
        verify_w70_foundation_gate_receipt(path, root=ROOT)


def test_quality_runner_checks_checked_in_receipt() -> None:
    completed = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            "scripts/quality/run_w70_s8_01_foundation_gate.py",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "w70_s8_01_foundation_gate=pass mode=check" in completed.stdout


def test_non_deterministic_compiler_output_fails_closed(monkeypatch) -> None:
    real_compiler = gate_module.NslCompiler
    calls = 0

    class NonDeterministicCompiler:
        def __init__(self, catalog) -> None:
            self._delegate = real_compiler(catalog)

        def compile(self, source):
            nonlocal calls
            calls += 1
            compiled = self._delegate.compile(source)
            if calls == 2:
                return SimpleNamespace(
                    skill=compiled.skill,
                    nso_bytes=compiled.nso_bytes + b"drift",
                )
            return compiled

    monkeypatch.setattr(gate_module, "NslCompiler", NonDeterministicCompiler)
    with pytest.raises(W70FoundationGateError, match="non-deterministic"):
        build_w70_foundation_gate_receipt(ROOT)


def test_status_only_profile_cannot_compile_even_if_compiler_is_replaced(
    monkeypatch,
) -> None:
    real_compiler = gate_module.NslCompiler

    class IncorrectlyPermissiveCompiler:
        def __init__(self, catalog) -> None:
            self._delegate = real_compiler(catalog)

        def compile(self, source):
            if "STATUS_ONLY_NEGATIVE" in source:
                valid = (
                    ROOT
                    / "domains/mybee/skills/foundation_gate/d04_read_profile.ns"
                ).read_text(encoding="utf-8")
                return self._delegate.compile(valid)
            return self._delegate.compile(source)

    monkeypatch.setattr(gate_module, "NslCompiler", IncorrectlyPermissiveCompiler)
    with pytest.raises(W70FoundationGateError, match="status-only.*admitted"):
        build_w70_foundation_gate_receipt(ROOT)


def test_every_fully_typed_domain_semantics_pair_needs_a_compile_profile(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gate_module,
        "_POSITIVE_PROFILES",
        tuple(
            item
            for item in gate_module._POSITIVE_PROFILES
            if item["profile_id"] != "D12_READ"
        ),
    )
    with pytest.raises(W70FoundationGateError, match="missing compiler profile"):
        build_w70_foundation_gate_receipt(ROOT)


def test_alias_resolution_drift_fails_the_gate(monkeypatch) -> None:
    class DriftedRegistry:
        @staticmethod
        def resolve(requested):
            return SimpleNamespace(
                canonical_operation="FINANCE.PROJECT_PNL.GET",
                alias_applied=True,
                to_projection=dict,
            )

    monkeypatch.setattr(gate_module, "DEFAULT_OPERATION_REGISTRY", DriftedRegistry())
    with pytest.raises(W70FoundationGateError, match="alias resolution drift"):
        build_w70_foundation_gate_receipt(ROOT)


def test_unexpected_negative_compile_code_fails_the_gate(monkeypatch) -> None:
    monkeypatch.setattr(gate_module, "_ERROR_CODE", re.compile(r"\[(OTHER-\d+)\]"))
    with pytest.raises(W70FoundationGateError, match="unexpected status-only"):
        build_w70_foundation_gate_receipt(ROOT)


def test_canonical_operation_must_not_resolve_as_alias(monkeypatch) -> None:
    real_registry = gate_module.DEFAULT_OPERATION_REGISTRY

    class CanonicalAliasRegistry:
        @staticmethod
        def resolve(requested):
            resolved = real_registry.resolve(requested)
            if not resolved.alias_applied:
                return SimpleNamespace(
                    canonical_operation=resolved.canonical_operation,
                    alias_applied=True,
                )
            return resolved

    monkeypatch.setattr(
        gate_module, "DEFAULT_OPERATION_REGISTRY", CanonicalAliasRegistry()
    )
    with pytest.raises(W70FoundationGateError, match="resolved as alias"):
        build_w70_foundation_gate_receipt(ROOT)


def test_unreadable_artifact_hash_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(W70FoundationGateError, match="unreadable artifact"):
        gate_module._byte_hash(tmp_path / "missing")
