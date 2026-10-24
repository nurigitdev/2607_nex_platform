from __future__ import annotations

import os

import pytest
from run_p8_s82_worker_crash_after_checkpoint import (
    SMOKE_ENV,
    run_p8_s82_worker_crash_after_checkpoint,
)

pytestmark = pytest.mark.skipif(
    os.getenv(SMOKE_ENV) != "1",
    reason="Protected P8-S82 worker-crash-after-checkpoint smoke is disabled",
)


def test_actual_postgres_restart_restores_exact_wait_and_resume_identity() -> None:
    result = run_p8_s82_worker_crash_after_checkpoint(execute=True)

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["checks_passed"] == result["checks_total"]
    assert result["decision"] == {
        "worker_crash_after_checkpoint_closed": True,
        "approval_semantic_count_per_suspension": 1,
        "checkpoint_consume_count_per_resume": 1,
    }
