from __future__ import annotations

import json
import os

import pytest
import run_p7_ca02_work_delegate_denied_postgres as smoke

AE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"
WC_URL = "postgresql://nex_wc_user:test-secret@127.0.0.1:5432/nex_wc_test"
OA_URL = "postgresql://nex_oa_user:test-secret@127.0.0.1:5432/nex_oa_test"


def _environment() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.AE_DATABASE_ENV: AE_URL,
        smoke.WC_DATABASE_ENV: WC_URL,
        smoke.OA_DATABASE_ENV: OA_URL,
    }


def test_ca02_negative_smoke_is_protected_and_rejects_non_test_targets():
    assert smoke.run_p7_ca02_work_delegate_denied_postgres({})["status"] == "SKIPPED"
    for database_env in (
        smoke.AE_DATABASE_ENV,
        smoke.WC_DATABASE_ENV,
        smoke.OA_DATABASE_ENV,
    ):
        env = _environment()
        env[database_env] = env[database_env].replace("_test", "_dev")
        evidence = smoke.run_p7_ca02_work_delegate_denied_postgres(env)
        assert evidence["failure_code"] == "target_not_allowed"


def test_ca02_negative_smoke_summary_and_failure_are_metadata_safe():
    failure = smoke._failure("expected", "bounded detail")  # noqa: SLF001
    assert "fail" in smoke.summary_line(failure)
    assert failure["actual_postgres"] is False


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required for protected PostgreSQL smoke",
)
def test_ca02_actual_postgres_denies_missing_delegate_with_zero_mutation():
    evidence = smoke.run_p7_ca02_work_delegate_denied_postgres()
    assert evidence["status"] == "PASS", evidence
    assert evidence["actual_postgres"] is True
    assert evidence["actual_remote_provider"] is False
    assert evidence["migration_heads"]["nex-wc"] == ("1003_wc_work_item_authorization")
    assert evidence["authorization"] == {
        "effective_authorization_calls": 1,
        "work_delegate_gate_calls": 1,
        "work_delegate_granted": False,
    }
    assert evidence["row_counts"]["wc_work_item"] == 0
    assert evidence["row_counts"]["wc_assignment"] == 0
    assert evidence["row_counts"]["wc_claim"] == 0
    assert evidence["row_counts"]["claim_execution_handoff"] == 0
    assert evidence["row_counts"]["child_agent_execution"] == 0
    assert evidence["row_counts"]["child_runtime_job"] == 0
    assert evidence["cleanup_counts"]["wc_remaining"] == 0
    assert evidence["cleanup_counts"]["oa_remaining"] == 0
    serialized = json.dumps(evidence, sort_keys=True)
    assert "nuri1004" not in serialized
    assert "test-secret" not in serialized
