from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import nex_runtime.production_tls_lifecycle as tls
from nex_runtime.production_tls_lifecycle import (
    ProductionTlsLifecycleError,
    build_production_tls_lifecycle_plan,
    certificate_expiry_alert,
    evaluate_production_tls_lifecycle,
    production_tls_lifecycle_projection,
)
from run_platform_production_tls_lifecycle import (
    NOW,
    _certificate,
    _tls_v2_environment,
)


ROOT = Path(__file__).resolve().parents[1]


def plan():
    return build_production_tls_lifecycle_plan(
        _tls_v2_environment(ROOT),
        _certificate("current", "v1", "ACTIVE", NOW - timedelta(days=2), NOW + timedelta(days=40)),
        _certificate("candidate", "v2", "CANDIDATE", NOW - timedelta(hours=2), NOW + timedelta(days=90)),
        root=ROOT,
    )


def test_tls_lifecycle_stages_overlaps_verifies_and_rolls_back() -> None:
    value = plan()
    staged = evaluate_production_tls_lifecycle(value, observed_at=NOW, activation_attempted=False, candidate_probe_verified=False)
    assert staged.status == "STAGED"
    overlap = evaluate_production_tls_lifecycle(value, observed_at=NOW, activation_attempted=True, candidate_probe_verified=True)
    assert overlap.status == "OVERLAP_VERIFYING"
    verified = evaluate_production_tls_lifecycle(
        value, observed_at=NOW, activation_attempted=True, candidate_probe_verified=True, candidate_verified_at=NOW - timedelta(hours=2)
    )
    assert verified.status == "VERIFIED"
    assert verified.retire_current_approved is True
    rollback = evaluate_production_tls_lifecycle(value, observed_at=NOW, activation_attempted=True, candidate_probe_verified=False)
    assert rollback.status == "ROLLBACK_REQUIRED"
    assert rollback.rollback_to_current_required is True
    projection = production_tls_lifecycle_projection(value, verified)
    assert projection["application_private_key_mount_allowed"] is False
    assert projection["certificate_pem_included"] is False


def test_current_expiry_or_revocation_blocks_lifecycle() -> None:
    value = plan()
    expired = replace(value, current=replace(value.current, not_after=NOW))
    assert evaluate_production_tls_lifecycle(expired, observed_at=NOW, activation_attempted=True, candidate_probe_verified=True).status == "BLOCKED_CURRENT_CERTIFICATE"
    revoked = replace(value, current=replace(value.current, state="REVOKED"))
    assert evaluate_production_tls_lifecycle(revoked, observed_at=NOW, activation_attempted=True, candidate_probe_verified=True).status == "BLOCKED_CURRENT_CERTIFICATE"


@pytest.mark.parametrize(
    "current_change,candidate_change,message",
    [
        ({"private_key_exposed": True}, {}, "private key exposure"),
        ({"dns_name_count": 0}, {}, "DNS coverage"),
        ({"state": "OTHER"}, {}, "state is invalid"),
        ({"certificate_id": ""}, {}, "metadata is incomplete"),
        ({"not_after": NOW - timedelta(days=3)}, {}, "validity window"),
        ({}, {"certificate_id": "current"}, "identity must change"),
        ({}, {"version": "v1"}, "version must change"),
        ({}, {"version": "v3"}, "reference version mismatch"),
        ({"not_after": NOW}, {"not_before": NOW - timedelta(minutes=30)}, "overlap is too short"),
    ],
)
def test_plan_rejects_certificate_policy_drift(current_change, candidate_change, message) -> None:
    current = _certificate("current", "v1", "ACTIVE", NOW - timedelta(days=2), NOW + timedelta(days=40))
    candidate = _certificate("candidate", "v2", "CANDIDATE", NOW - timedelta(hours=2), NOW + timedelta(days=90))
    with pytest.raises(ProductionTlsLifecycleError, match=message):
        build_production_tls_lifecycle_plan(
            _tls_v2_environment(ROOT), replace(current, **current_change), replace(candidate, **candidate_change), root=ROOT
        )


def test_expiry_alerts_timestamp_validation_and_projection_guard() -> None:
    value = plan()
    assert certificate_expiry_alert(replace(value.current, not_after=NOW + timedelta(days=30)), observed_at=NOW) == "WARNING"
    assert certificate_expiry_alert(replace(value.current, not_after=NOW + timedelta(days=7)), observed_at=NOW) == "CRITICAL"
    assert certificate_expiry_alert(replace(value.current, not_after=NOW), observed_at=NOW) == "EXPIRED"
    assert certificate_expiry_alert(replace(value.current, not_after=NOW + timedelta(days=31)), observed_at=NOW) == "OK"
    with pytest.raises(ValueError, match="timezone"):
        certificate_expiry_alert(value.current, observed_at=datetime(2026, 10, 7))
    with pytest.raises(TypeError, match="datetime"):
        certificate_expiry_alert(value.current, observed_at="bad")
    decision = evaluate_production_tls_lifecycle(value, observed_at=NOW, activation_attempted=False, candidate_probe_verified=False)
    with pytest.raises(ProductionTlsLifecycleError, match="plan is invalid"):
        evaluate_production_tls_lifecycle(replace(value, termination_mode="other"), observed_at=NOW, activation_attempted=False, candidate_probe_verified=False)
    with pytest.raises(ProductionTlsLifecycleError, match="decision is invalid"):
        production_tls_lifecycle_projection(value, replace(decision, status="OTHER"))


def test_post_admission_generation_reference_and_timestamp_defenses() -> None:
    environment = _tls_v2_environment(ROOT)
    current = _certificate("current", "v1", "ACTIVE", NOW - timedelta(days=2), NOW + timedelta(days=40))
    candidate = _certificate("candidate", "v2", "CANDIDATE", NOW - timedelta(hours=2), NOW + timedelta(days=90))
    environment["NEX_TLS_GENERATION"] = "config:valid-but-wrong-kind"
    with pytest.raises(ProductionTlsLifecycleError, match="generation is invalid"):
        build_production_tls_lifecycle_plan(environment, current, candidate, root=ROOT)
    environment["NEX_TLS_GENERATION"] = "tls:2026-10-07.2"
    with pytest.raises(ProductionTlsLifecycleError, match="timestamps are invalid"):
        build_production_tls_lifecycle_plan(
            environment,
            replace(current, not_after=datetime(2026, 11, 1)),
            candidate,
            root=ROOT,
        )
    with pytest.raises(ProductionTlsLifecycleError, match="reference version"):
        tls._reference_version("tls://managed/no-version")
    with pytest.raises(ProductionTlsLifecycleError, match="reference version"):
        tls._reference_version("tls:/missing-host@v2")
