from __future__ import annotations

from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path

import pytest

from nex_runtime.platform_trust_scope_policy import (
    PLATFORM_TRUST_GRANTS,
    PlatformTrustGrant,
    platform_trust_scope_policy,
    validate_platform_trust_scope_policy,
)


policy_module = importlib.import_module("nex_runtime.platform_trust_scope_policy")


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts/smoke/run_platform_trust_scope_policy.py"


def _runner_module():
    spec = importlib.util.spec_from_file_location("platform_trust_scope_policy_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_trust_scope_policy_freezes_exact_s134_grants() -> None:
    result = platform_trust_scope_policy()

    assert validate_platform_trust_scope_policy() == ()
    assert result["grant_count"] == 8
    assert result["service_ids"] == ["nex-ae-api", "nex-ag", "nex-cx", "nex-mo"]
    assert result["audiences"] == ["nex-ag", "nex-cx", "nex-mo", "nex-oa"]
    assert result["active_claim_route_class"] == "CREDENTIAL"
    assert result["raw_tokens_included"] is False
    assert {item["grant_id"] for item in result["grants"]} == {
        "ae_to_oa_call",
        "ae_to_cx_call",
        "cx_to_mo_call",
        "ae_to_ag_call",
        "ae_to_oa_introspection",
        "cx_to_oa_introspection",
        "mo_to_oa_introspection",
        "ag_to_oa_introspection",
    }


@pytest.mark.parametrize(
    ("replacement", "expected_issue"),
    [
        ({"grant_id": " bad "}, "grant_id_invalid"),
        ({"service_id": "nex-unknown"}, "service_id_invalid:ae_to_oa_call"),
        ({"audience": "nex-ae-api"}, "audience_invalid:ae_to_oa_call"),
        ({"consumer_service_id": "nex-cx"}, "consumer_invalid:ae_to_oa_call"),
        ({"scopes": ("document:read",)}, "scope_invalid:ae_to_oa_call"),
        ({"environment_name": "WRONG"}, "environment_invalid:ae_to_oa_call"),
    ],
)
def test_platform_trust_scope_policy_detects_malformed_grants(
    monkeypatch: pytest.MonkeyPatch,
    replacement: dict[str, object],
    expected_issue: str,
) -> None:
    malformed = replace(PLATFORM_TRUST_GRANTS[0], **replacement)
    monkeypatch.setattr(
        policy_module,
        "PLATFORM_TRUST_GRANTS",
        (malformed, *PLATFORM_TRUST_GRANTS[1:]),
    )
    assert expected_issue in validate_platform_trust_scope_policy()


def test_platform_trust_scope_policy_detects_duplicate_and_incomplete_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy_module,
        "PLATFORM_TRUST_GRANTS",
        (PLATFORM_TRUST_GRANTS[0], PLATFORM_TRUST_GRANTS[0]),
    )
    issues = validate_platform_trust_scope_policy()
    assert "grant_id_duplicate" in issues
    assert "grant_inventory_invalid" in issues


def test_platform_trust_grant_projection_uses_json_scopes() -> None:
    grant = PlatformTrustGrant(
        grant_id="test",
        service_id="nex-cx",
        audience="nex-mo",
        scopes=("service:call",),
        purpose="model_route",
        consumer_service_id="nex-cx",
        environment_name="NEX_CX_TO_MO_SERVICE_TOKEN",
    )
    assert grant.to_wire()["scopes"] == ["service:call"]


def test_platform_trust_scope_policy_runner_and_summary(capsys: pytest.CaptureFixture[str]) -> None:
    module = _runner_module()
    result = module.run_platform_trust_scope_policy(ROOT)

    assert result["status"] == "PASS"
    assert result["checks"] == {
        "grant_policy_valid": True,
        "active_claim_route_registered": True,
        "active_claim_route_is_sensitive": True,
        "active_claim_requires_service_scope": True,
        "raw_tokens_excluded": True,
    }
    assert module.main(["--summary"]) == 0
    assert (
        "platform_trust_scope_policy=pass grants=8 services=4 audiences=4 next=1338"
        in capsys.readouterr().out
    )
