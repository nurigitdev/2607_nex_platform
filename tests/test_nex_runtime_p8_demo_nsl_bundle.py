from __future__ import annotations

import json
from pathlib import Path

import pytest
from nex_runtime.demo_fixture import load_demo_business_fixture
from nex_runtime.demo_nsl_bundle import (
    DemoNslBundleError,
    load_demo_nsl_runtime_bundle,
    verify_demo_nsl_runtime_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "deployment/locks/p8-demo-nsl-runtime-bundle.v1.json"
NSL_SOURCE = Path("/home/tprover/2608_nsl")
WHEEL = (
    ROOT
    / "reports/deployment/p8-nsl-v0.2.1-wheel"
    / "nex_skill_language-0.2.1-py3-none-any.whl"
)


def test_demo_nsl_bundle_manifest_admits_locked_local_artifacts() -> None:
    bundle = load_demo_nsl_runtime_bundle(MANIFEST)

    readiness = verify_demo_nsl_runtime_bundle(
        bundle,
        wheel_path=WHEEL,
        skill_root=NSL_SOURCE / bundle.skill_source_directory,
        demo_fixture_path=ROOT / bundle.demo_fixture_path,
        base_fixture_path=ROOT / bundle.base_fixture_path,
    )

    assert readiness["status"] == "PASS"
    assert bundle.admitted_at == "2026-10-25T00:00:00Z"
    assert readiness["skill_id"] == "FINANCE.VOUCHER_DRAFT_CREATE"
    assert readiness["skill_file_count"] == 8
    assert readiness["secret_included"] is False


def test_demo_nsl_bundle_rejects_digest_drift(tmp_path: Path) -> None:
    bundle = load_demo_nsl_runtime_bundle(MANIFEST)
    wrong_wheel = tmp_path / bundle.wheel_filename
    wrong_wheel.write_bytes(b"drift")

    with pytest.raises(DemoNslBundleError, match="digest"):
        verify_demo_nsl_runtime_bundle(
            bundle,
            wheel_path=wrong_wheel,
            skill_root=NSL_SOURCE / bundle.skill_source_directory,
            demo_fixture_path=ROOT / bundle.demo_fixture_path,
            base_fixture_path=ROOT / bundle.base_fixture_path,
        )


def test_demo_fixture_loader_derives_vo00_without_mutating_base() -> None:
    document, business = load_demo_business_fixture(
        ROOT / "scripts/deployment/data/p8_demo_vo00_fixture.v1.json",
        base_fixture_path=ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json",
    )

    assert document["tenant"]["tenant_id"] == "VO00"
    assert business["tenant"]["tenant_id"] == "VO00"
    assert business["fixture_hash"] != document["base_fixture"]["fixture_hash"]
    base = json.loads(
        (ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert base["tenant"]["tenant_id"] == "p8-golden-a"
