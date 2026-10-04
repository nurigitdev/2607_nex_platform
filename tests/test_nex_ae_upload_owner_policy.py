from __future__ import annotations

from pathlib import Path

import pytest

import run_ae_protected_upload_owner_policy as smoke
from nex_ae_api.upload_owner_policy import (
    UploadOwnerPolicyError,
    enforce_upload_owner_policy,
    explicit_upload_owner_scope,
    normalize_upload_runtime_profile,
    upload_owner_policy_projection,
)


def test_runtime_profile_normalization_and_projection() -> None:
    assert normalize_upload_runtime_profile(None) == "local_mock"
    assert normalize_upload_runtime_profile(" TEST ") == "test"
    assert upload_owner_policy_projection("test") == {
        "policy_schema_version": "ae_upload_owner_policy.v1",
        "runtime_profile": "test",
        "protected": True,
        "browser_owner_authority": "oa_claim",
        "service_owner_authority": "explicit_payload",
        "local_owner_fallback_allowed": False,
        "local_owner_placeholders_allowed": False,
    }
    assert upload_owner_policy_projection("local_mock")["protected"] is False
    with pytest.raises(UploadOwnerPolicyError) as exc:
        normalize_upload_runtime_profile("preview")
    assert exc.value.error_code == "ae.upload_runtime_profile_invalid"
    assert str(exc.value) == exc.value.detail


def test_protected_policy_requires_explicit_non_placeholder_owner_scope() -> None:
    for payload, error_code in (
        ({}, "ae.upload_owner_scope_required"),
        ({"tenant_id": "tenant-a"}, "ae.upload_owner_scope_required"),
        (
            {"tenant_id": "local-tenant", "owner_user_id": "local-user"},
            "ae.upload_owner_scope_placeholder_forbidden",
        ),
    ):
        with pytest.raises(UploadOwnerPolicyError) as exc:
            enforce_upload_owner_policy(payload, runtime_profile="test")
        assert exc.value.error_code == error_code


def test_owner_scope_accepts_claim_shape_canonical_shape_and_local_mock() -> None:
    claim_payload = {"tenant_id": "tenant-a", "owner_user_id": "user-a"}
    canonical_payload = {
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-b"},
        }
    }
    legacy_payload = {
        "ownership_ref": {
            "legacy": {"tenant_id": "tenant-c", "owner_user_id": "user-c"}
        }
    }

    assert (
        enforce_upload_owner_policy(claim_payload, runtime_profile="test")
        == claim_payload
    )
    assert explicit_upload_owner_scope(canonical_payload) == ("tenant-b", "user-b")
    assert explicit_upload_owner_scope(legacy_payload) == ("tenant-c", "user-c")
    assert enforce_upload_owner_policy({}, runtime_profile="local_mock") == {}


def test_boundary_smoke_passes_and_failure_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    evidence = smoke.run_ae_protected_upload_owner_policy()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["next_slice"] == "1344"
    assert smoke.run_ae_protected_upload_owner_policy(tmp_path)["status"] == "FAIL"
    assert smoke._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert smoke._read_text(source) == "value"
    assert "checks=7/7" in smoke.summary_line(evidence)
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_protected_upload_owner_policy=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_ae_protected_upload_owner_policy", lambda: evidence)
    assert smoke.main(["--summary"]) == 0
    assert "next=1344" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_ae_protected_upload_owner_policy",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
