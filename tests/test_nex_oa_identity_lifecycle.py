from __future__ import annotations

import pytest

from nex_oa.identity_lifecycle import (
    OaIdentityLifecycleError,
    normalize_lifecycle_reason,
    normalize_lifecycle_revision,
    plan_membership_status_transition,
    plan_subject_status_transition,
)
import nex_oa.identity_lifecycle as lifecycle


def _subject(**overrides: object) -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "subject_id": "employee-1",
        "status": "ACTIVE",
        "revision": 2,
        **overrides,
    }


@pytest.mark.parametrize(
    ("current", "target", "terminal"),
    [
        ("ACTIVE", "DISABLED", False),
        ("ACTIVE", "DELETED", True),
        ("DISABLED", "ACTIVE", False),
        ("DISABLED", "DELETED", True),
    ],
)
def test_subject_transition_matrix(current: str, target: str, terminal: bool) -> None:
    result = plan_subject_status_transition(
        _subject(status=current),
        target_status=target,
        expected_revision=2,
        reason_code="admin.lifecycle-change",
    )

    assert result["previous_status"] == current
    assert result["target_status"] == target
    assert result["next_revision"] == 3
    assert result["changed"] is True
    assert result["terminal"] is terminal


def test_same_subject_status_is_idempotent_for_nested_snapshot() -> None:
    result = plan_subject_status_transition(
        {"subject": _subject()}, target_status="active", expected_revision="2"
    )

    assert result["changed"] is False
    assert result["next_revision"] == 2
    assert result["reason_code"] is None


def test_deleted_subject_is_terminal() -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_subject_status_transition(
            _subject(status="DELETED"),
            target_status="ACTIVE",
            expected_revision=2,
            reason_code="admin.restore",
        )

    assert caught.value.status_code == 409
    assert caught.value.error_code == "oa.subject_transition_invalid"
    assert "DELETED to ACTIVE" in str(caught.value)


def test_stale_subject_revision_fails_closed() -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_subject_status_transition(
            _subject(),
            target_status="DISABLED",
            expected_revision=1,
            reason_code="admin.disable",
        )

    assert caught.value.status_code == 409
    assert caught.value.error_code == "oa.lifecycle_revision_conflict"


@pytest.mark.parametrize("value", [None, "", " ", "UPPER CASE", "a", "a" * 65, 42])
def test_changed_subject_requires_valid_reason(value: object) -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_subject_status_transition(
            _subject(),
            target_status="DISABLED",
            expected_revision=2,
            reason_code=value,
        )

    assert caught.value.error_code == "oa.lifecycle_reason_invalid"


@pytest.mark.parametrize("value", [True, False, None, 0, -1, "1.0", " 1", object()])
def test_revision_validation_rejects_noncanonical_values(value: object) -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        normalize_lifecycle_revision(value)

    assert caught.value.error_code == "oa.lifecycle_revision_invalid"


def test_reason_normalization_and_optional_none() -> None:
    assert normalize_lifecycle_reason("  admin.Disable-User ", required=True) == "admin.disable-user"
    assert normalize_lifecycle_reason(None, required=False) is None


def test_nested_subject_must_be_mapping() -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_subject_status_transition(
            {"subject": "invalid"},
            target_status="ACTIVE",
            expected_revision=1,
        )

    assert caught.value.error_code == "oa.subject_record_invalid"


def _membership(**overrides: object) -> dict[str, object]:
    return {
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "subject_ref": {"type": "oa.user", "id": "employee-1"},
        "status": "ACTIVE",
        "revision": 4,
        **overrides,
    }


@pytest.mark.parametrize(
    ("current", "target", "revoke"),
    [("ACTIVE", "DISABLED", True), ("DISABLED", "ACTIVE", False)],
)
def test_membership_transition_matrix(current: str, target: str, revoke: bool) -> None:
    result = plan_membership_status_transition(
        _membership(status=current),
        target_status=target,
        expected_revision=4,
        reason_code="admin.membership-change",
    )

    assert result["previous_status"] == current
    assert result["target_status"] == target
    assert result["next_revision"] == 5
    assert result["revoke_active_sessions"] is revoke
    assert result["restore_prior_sessions"] is False


def test_membership_same_state_is_idempotent_with_flat_ids() -> None:
    result = plan_membership_status_transition(
        {
            "membership": {
                "tenant_id": "tenant-a",
                "subject_id": "employee-1",
                "status": "ACTIVE",
                "revision": 1,
            }
        },
        target_status="ACTIVE",
        expected_revision=1,
    )

    assert result["changed"] is False
    assert result["next_revision"] == 1
    assert result["revoke_active_sessions"] is False


def test_membership_stale_revision_fails_closed() -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_membership_status_transition(
            _membership(),
            target_status="DISABLED",
            expected_revision=3,
            reason_code="admin.disable",
        )

    assert caught.value.error_code == "oa.lifecycle_revision_conflict"


def test_membership_record_must_be_mapping() -> None:
    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_membership_status_transition(
            {"membership": []}, target_status="ACTIVE", expected_revision=1
        )

    assert caught.value.error_code == "oa.membership_record_invalid"


def test_membership_transition_fails_closed_for_unknown_normalized_state(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        lifecycle, "normalize_membership_status", lambda value: str(value).upper()
    )

    with pytest.raises(OaIdentityLifecycleError) as caught:
        plan_membership_status_transition(
            _membership(),
            target_status="REVOKED",
            expected_revision=4,
            reason_code="admin.revoke",
        )

    assert caught.value.error_code == "oa.membership_transition_invalid"
