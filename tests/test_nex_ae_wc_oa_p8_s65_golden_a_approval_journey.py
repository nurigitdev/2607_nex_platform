from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s65_golden_a_approval_journey as smoke
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref
from p8_golden_a_fixture import load_golden_a_fixture


def test_p8_s65_live_gate_is_explicitly_protected() -> None:
    assert (
        smoke.run_p8_s65_golden_a_approval_journey({}, execute=False)["status"]
        == "SKIPPED"
    )
    assert (
        smoke.run_p8_s65_golden_a_approval_journey({}, execute=True)["status"]
        == "SKIPPED"
    )


def test_database_target_guard_requires_exact_test_role_and_database() -> None:
    smoke._require_database_target(
        "postgresql+psycopg://nex_oa_user:secret@localhost/nex_oa_test",
        role="nex_oa_user",
        database="nex_oa_test",
        label="OA",
    )
    with pytest.raises(smoke.P8S65SmokeError, match="is required"):
        smoke._require_database_target(
            "", role="nex_oa_user", database="nex_oa_test", label="OA"
        )
    with pytest.raises(smoke.P8S65SmokeError, match="must target"):
        smoke._require_database_target(
            "postgresql+psycopg://other:secret@localhost/nex_oa_test",
            role="nex_oa_user",
            database="nex_oa_test",
            label="OA",
        )


def test_failure_evidence_redacts_database_password() -> None:
    result = smoke.run_p8_s65_golden_a_approval_journey(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: (
                "postgresql+psycopg://nex_ae_user:private@localhost/wrong"
            ),
            smoke.WC_DATABASE_ENV: (
                "postgresql+psycopg://nex_wc_user:private@localhost/nex_wc_test"
            ),
            smoke.OA_DATABASE_ENV: (
                "postgresql+psycopg://nex_oa_user:private@localhost/nex_oa_test"
            ),
        },
        execute=True,
    )

    assert result["status"] == "FAIL"
    assert "private" not in json.dumps(result)


def test_golden_a_profile_uses_exact_project_account_period_and_amount(
    tmp_path: Path,
) -> None:
    fixture = load_golden_a_fixture()
    profile = tmp_path / "controlled.profile.json"
    profile.write_text("{}\n", encoding="utf-8")
    (tmp_path / "input.json").write_text("{}\n", encoding="utf-8")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    tool_fixture = {
        "tools": [
            {
                "tool_id": tool_id,
                "cases": [{"arguments": {key: "old"}, "result": {key: "old"}}],
            }
            for tool_id, key in (
                ("ACCOUNT.GET_ACCOUNT", "account_code"),
                ("PROJECT.GET_PROJECT", "project_code"),
                ("FINANCE.GET_ACCOUNTING_PERIOD", "accounting_period"),
            )
        ]
    }
    tool_fixture["tools"].append(
        {
            "tool_id": "FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND",
            "cases": [{"arguments": {}, "result": {}}],
        }
    )
    (fixture_dir / "success.json").write_text(
        json.dumps(tool_fixture), encoding="utf-8"
    )

    smoke._customize_profile(profile, fixture)

    input_value = json.loads((tmp_path / "input.json").read_text(encoding="utf-8"))
    tools = {
        item["tool_id"]: item
        for item in json.loads(
            (fixture_dir / "success.json").read_text(encoding="utf-8")
        )["tools"]
    }
    assert input_value == {
        "tenant_id": "p8-golden-a",
        "requester_id": "employee-1001",
        "account_code": "TRAVEL",
        "counter_account_code": "CASH",
        "project_code": "PROJECT-A-2",
        "accounting_period": "2026-10",
        "amount": {"$type": "Money", "amount": "84000.00", "currency": "KRW"},
        "transaction_date": "2026-10-23",
        "voucher_type": "GENERAL",
        "economic_category": "TRAVEL",
        "settlement_method": "CASH",
        "description_text": "Golden A travel expense draft",
    }
    assert (
        tools["ACCOUNT.GET_ACCOUNT"]["cases"][0]["result"]["account_code"] == "TRAVEL"
    )
    assert (
        tools["PROJECT.GET_PROJECT"]["cases"][0]["arguments"]["project_code"]
        == "PROJECT-A-2"
    )
    command = tools["FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND"]["cases"][0]["result"]
    assert command["project_ref"]["id"] == "82000000-0000-4000-8000-000000000001"
    assert [line["signed_amount"] for line in command["lines"]] == [
        "84000.00",
        "-84000.00",
    ]
    assert "nsl_approval_request_id" not in command
    assert nsl_write_payload_hash_ref(command) == (
        "sha256:240a7e83a1b3355ba98b5473cc239f1aea6a318b17e53e385c01837666fb8eb9"
    )


def test_summary_is_bounded_and_excludes_private_lineage() -> None:
    line = smoke.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "provider": {"model_ref": "Qwen3.5-4B"},
            "approval": {"approval_status": "APPROVED", "resume_state": "DONE"},
            "checks": {"one": True, "two": True},
        }
    )

    assert "checks=2/2" in line
    assert "approval=APPROVED" in line
    assert "resume=DONE" in line
    assert "tenant" not in line


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1"
    or any(not os.getenv(key) for key in smoke.EXPECTED_DATABASES),
    reason="Protected P8-S65 PostgreSQL and live-provider gate is disabled",
)
def test_actual_postgres_live_provider_golden_a_approval_journey() -> None:
    result = smoke.run_p8_s65_golden_a_approval_journey(execute=True)

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["actual_remote_provider"] is True
    assert result["decision"] == {
        "p8_s65_closed": True,
        "eos_write_enabled": False,
        "next_slice": "P8-S66",
    }
