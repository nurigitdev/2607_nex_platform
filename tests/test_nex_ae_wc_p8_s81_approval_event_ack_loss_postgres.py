from __future__ import annotations

import os

import pytest
from run_p8_s81_approval_event_ack_loss import (
    SMOKE_ENV,
    run_p8_s81_approval_event_ack_loss,
)

pytestmark = pytest.mark.skipif(
    os.getenv(SMOKE_ENV) != "1",
    reason="Protected P8-S81 approval event ACK-loss smoke is disabled",
)


def test_actual_postgres_ack_loss_creates_one_resume_and_checkpoint_consume() -> None:
    result = run_p8_s81_approval_event_ack_loss(execute=True)

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["checks_passed"] == result["checks_total"]
    assert result["decision"] == {
        "approval_event_ack_loss_closed": True,
        "semantic_resume_count_per_event": 1,
        "checkpoint_consume_count_per_event": 1,
    }
