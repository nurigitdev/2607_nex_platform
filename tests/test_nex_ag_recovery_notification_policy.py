from __future__ import annotations

import nex_ag.recovery_notification_policy as policy


def test_recovery_notification_policy_safe_defaults() -> None:
    result = policy.build_recovery_notification_policy({})

    assert result["notification_policy_schema_version"] == policy.RECOVERY_NOTIFICATION_POLICY_SCHEMA_VERSION
    assert result["policy_status"] == "ENABLED"
    assert result["enabled"] is True
    assert result["delivery_enabled"] is False
    assert result["evaluation_mode"] == "deterministic_preview_only"
    assert result["minimum_severity"] == "WARNING"
    assert result["repeat_window_seconds"] == 900
    assert result["critical_bypass_suppression"] is True
    assert result["preview_channels"] == ["operations_dashboard"]
    assert result["new_tables_required"] is False
    assert result["guardrails"]["external_provider_invocation_allowed"] is False
    assert not any(result["redaction"].values())


def test_recovery_notification_policy_explicit_overrides() -> None:
    result = policy.build_recovery_notification_policy(
        {
            policy.RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV: "off",
            policy.RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV: "yes",
            policy.RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV: "critical",
            policy.RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV: "1200",
            policy.RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV: "0",
        }
    )

    assert result["policy_status"] == "DISABLED"
    assert result["enabled"] is False
    assert result["delivery_enabled"] is True
    assert result["minimum_severity"] == "CRITICAL"
    assert result["repeat_window_seconds"] == 1200
    assert result["critical_bypass_suppression"] is False


def test_recovery_notification_policy_invalid_values_use_defaults() -> None:
    result = policy.build_recovery_notification_policy(
        {
            policy.RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV: "perhaps",
            policy.RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV: "later",
            policy.RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV: "fatal",
            policy.RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV: "not-int",
            policy.RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV: "maybe",
        }
    )

    assert result["enabled"] is True
    assert result["delivery_enabled"] is False
    assert result["minimum_severity"] == "WARNING"
    assert result["repeat_window_seconds"] == 900
    assert result["critical_bypass_suppression"] is True


def test_recovery_notification_policy_bounds_repeat_window() -> None:
    below = policy.build_recovery_notification_policy(
        {policy.RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV: "1"}
    )
    above = policy.build_recovery_notification_policy(
        {policy.RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV: "999999"}
    )

    assert below["repeat_window_seconds"] == 60
    assert above["repeat_window_seconds"] == 86400


def test_recovery_notification_policy_boolean_spellings() -> None:
    for value in ("1", "TRUE", " yes ", "On"):
        assert policy._env_flag(value, default=False) is True
    for value in ("0", "FALSE", " no ", "Off"):
        assert policy._env_flag(value, default=True) is False
    assert policy._env_flag(None, default=True) is True


def test_recovery_notification_policy_reads_process_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv(policy.RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV, "info")
    monkeypatch.setenv(policy.RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS_ENV, "60")

    result = policy.build_recovery_notification_policy()

    assert result["minimum_severity"] == "INFO"
    assert result["repeat_window_seconds"] == 60


def test_recovery_notification_policy_helper_edge_cases() -> None:
    assert policy._severity(None, default="ERROR") == "ERROR"
    assert policy._severity(" warning ", default="ERROR") == "WARNING"
    assert policy._bounded_int(None, default=7, minimum=1, maximum=10) == 7
