from __future__ import annotations

import nex_ag.liveness_ack_expiry_automation as automation


def test_ack_expiry_automation_policy_is_disabled_and_bounded_by_default() -> None:
    policy = automation.build_liveness_ack_expiry_automation_policy({})

    assert policy["automation_policy_schema_version"] == (
        automation.ACK_EXPIRY_AUTOMATION_POLICY_SCHEMA_VERSION
    )
    assert policy["policy_status"] == "DISABLED"
    assert policy["enabled"] is False
    assert policy["batch_limit"] == 50
    assert policy["cadence_seconds"] == 60
    assert policy["requires_confirm_tick"] is True
    assert policy["execution_mode"] == "externally_scheduled_bounded_run_once"
    assert policy["source_table"] == "ag_op_review_ack_state"
    assert policy["event_table"] == "service_operational_events"
    assert policy["new_tables_required"] is False
    assert policy["continuous_loop_started"] is False
    assert policy["subprocess_started"] is False
    assert all(policy["guardrails"].values()) is False
    assert policy["guardrails"]["disabled_by_default"] is True
    assert policy["guardrails"]["source_liveness_projection_mutated"] is False
    assert policy["redaction"] == {
        "raw_comments_included": False,
        "raw_idempotency_keys_included": False,
        "raw_payloads_included": False,
        "database_urls_included": False,
        "tokens_included": False,
    }


def test_ack_expiry_automation_policy_accepts_explicit_enablement() -> None:
    policy = automation.build_liveness_ack_expiry_automation_policy(
        {
            automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "yes",
            automation.ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV: "75",
            automation.ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS_ENV: "300",
        }
    )

    assert policy["policy_status"] == "ENABLED"
    assert policy["enabled"] is True
    assert policy["batch_limit"] == 75
    assert policy["cadence_seconds"] == 300


def test_ack_expiry_automation_policy_bounds_numeric_configuration() -> None:
    low = automation.build_liveness_ack_expiry_automation_policy(
        {
            automation.ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV: "0",
            automation.ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS_ENV: "1",
        }
    )
    high = automation.build_liveness_ack_expiry_automation_policy(
        {
            automation.ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV: "9999",
            automation.ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS_ENV: "9999",
        }
    )

    assert low["batch_limit"] == 1
    assert low["cadence_seconds"] == 10
    assert high["batch_limit"] == 200
    assert high["cadence_seconds"] == 3600


def test_ack_expiry_automation_policy_uses_defaults_for_invalid_values() -> None:
    policy = automation.build_liveness_ack_expiry_automation_policy(
        {
            automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "maybe",
            automation.ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV: "bad",
            automation.ACK_EXPIRY_AUTOMATION_CADENCE_SECONDS_ENV: "bad",
        }
    )

    assert policy["enabled"] is False
    assert policy["batch_limit"] == 50
    assert policy["cadence_seconds"] == 60


def test_ack_expiry_automation_policy_boolean_normalization() -> None:
    for value in ("1", "TRUE", "on"):
        assert automation._env_flag(value, default=False) is True
    for value in ("0", "False", "no", "off", ""):
        assert automation._env_flag(value, default=True) is False
    assert automation._env_flag(None, default=True) is True
    assert automation._env_flag("unknown", default=True) is True


def test_ack_expiry_automation_policy_reads_process_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv(automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV, "1")
    monkeypatch.setenv(automation.ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV, "12")

    policy = automation.build_liveness_ack_expiry_automation_policy()

    assert policy["enabled"] is True
    assert policy["batch_limit"] == 12
