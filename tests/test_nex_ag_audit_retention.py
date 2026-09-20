from __future__ import annotations

import pytest

from nex_ag.audit_retention import (
    AG_AUDIT_RETENTION_POLICY_ID,
    AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION,
    AG_AUDIT_RETENTION_RECEIPT_TABLE,
    AgAuditRetentionPolicyError,
    build_ag_audit_retention_policy,
)


def test_default_policy_is_dry_run_and_mock_safe() -> None:
    policy = build_ag_audit_retention_policy({})

    assert policy["policy_schema_version"] == (
        AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION
    )
    assert policy["policy_id"] == AG_AUDIT_RETENTION_POLICY_ID
    assert policy["sources"] == [
        {
            "source_kind": "operational_event",
            "table_name": "service_operational_events",
            "identity_field": "event_id",
            "timestamp_field": "created_at",
            "retention_days": 365,
        },
        {
            "source_kind": "evidence_export",
            "table_name": "ag_ev_exports",
            "identity_field": "export_id",
            "timestamp_field": "updated_at",
            "retention_days": 365,
        },
    ]
    assert policy["archive"] == {
        "provider_mode": "mock",
        "recoverable_payload_required": True,
        "sealed_receipt_required": True,
        "receipt_table": AG_AUDIT_RETENTION_RECEIPT_TABLE,
        "digest_algorithm": "sha256",
        "grace_days": 30,
        "raw_payload_in_receipt": False,
    }
    assert policy["purge"] == {
        "dry_run_default": True,
        "execute_enabled": False,
        "explicit_confirmation_required": True,
        "same_transaction_recheck_required": True,
        "batch_size": 100,
        "hard_max_batch_size": 500,
    }


def test_policy_accepts_external_execute_overrides() -> None:
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "730",
            "NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS": "180",
            "NEX_AG_ARCHIVE_GRACE_DAYS": "15",
            "NEX_AG_RETENTION_BATCH_SIZE": "250",
            "NEX_AG_ARCHIVE_PROVIDER_MODE": " EXTERNAL ",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "yes",
        }
    )

    assert [item["retention_days"] for item in policy["sources"]] == [730, 180]
    assert policy["archive"]["provider_mode"] == "external"
    assert policy["archive"]["grace_days"] == 15
    assert policy["purge"]["execute_enabled"] is True
    assert policy["purge"]["batch_size"] == 250


@pytest.mark.parametrize(
    "environ",
    [
        {"NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "29"},
        {"NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "3651"},
        {"NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS": "0"},
        {"NEX_AG_ARCHIVE_GRACE_DAYS": "366"},
        {"NEX_AG_RETENTION_BATCH_SIZE": "501"},
    ],
)
def test_policy_rejects_out_of_range_values(environ: dict[str, str]) -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(environ)

    assert exc_info.value.error_code == "ag.retention.policy_value_out_of_range"
    assert str(exc_info.value) == exc_info.value.detail


@pytest.mark.parametrize("raw", ["invalid", "1.5"])
def test_policy_rejects_non_integer_value(raw: str) -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_AUDIT_EVENT_RETENTION_DAYS": raw}
        )

    assert exc_info.value.error_code == "ag.retention.policy_value_invalid"


def test_empty_values_use_defaults_and_false_alias_is_supported() -> None:
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": " ",
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "off",
        }
    )

    assert policy["sources"][0]["retention_days"] == 365
    assert policy["archive"]["provider_mode"] == "mock"
    assert policy["purge"]["execute_enabled"] is False


def test_policy_rejects_archive_grace_longer_than_retention() -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {
                "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "30",
                "NEX_AG_ARCHIVE_GRACE_DAYS": "31",
            }
        )

    assert exc_info.value.error_code == (
        "ag.retention.archive_grace_exceeds_retention"
    )


def test_policy_rejects_execute_with_mock_archive_provider() -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_RETENTION_EXECUTE_ENABLED": "true"}
        )

    assert exc_info.value.error_code == (
        "ag.retention.execute_requires_external_archive"
    )


def test_policy_rejects_invalid_provider_mode() -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_ARCHIVE_PROVIDER_MODE": "filesystem"}
        )

    assert exc_info.value.error_code == (
        "ag.retention.archive_provider_mode_invalid"
    )
    assert "external, mock" in exc_info.value.detail


@pytest.mark.parametrize("raw", ["sometimes", "2"])
def test_policy_rejects_invalid_boolean(raw: str) -> None:
    with pytest.raises(AgAuditRetentionPolicyError) as exc_info:
        build_ag_audit_retention_policy(
            {"NEX_AG_RETENTION_EXECUTE_ENABLED": raw}
        )

    assert exc_info.value.error_code == "ag.retention.policy_boolean_invalid"


@pytest.mark.parametrize("raw", ["1", "true", "on"])
def test_boolean_true_aliases_require_external_mode(raw: str) -> None:
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "external",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": raw,
        }
    )

    assert policy["purge"]["execute_enabled"] is True


@pytest.mark.parametrize("raw", ["0", "false", "no"])
def test_boolean_false_aliases_are_supported(raw: str) -> None:
    policy = build_ag_audit_retention_policy(
        {"NEX_AG_RETENTION_EXECUTE_ENABLED": raw}
    )

    assert policy["purge"]["execute_enabled"] is False
