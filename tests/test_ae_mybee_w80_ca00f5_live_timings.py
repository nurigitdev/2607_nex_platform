from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/deployment"))

import analyze_mybee_w80_ca00f5_live_timings as timings


def test_duration_rejects_non_monotonic_evidence():
    later = timings._timestamp("2026-01-01T00:00:01Z")
    earlier = timings._timestamp("2026-01-01T00:00:00Z")
    with pytest.raises(timings.TimingEvidenceError, match="not monotonic"):
        timings._milliseconds(later, earlier)


def test_provider_calls_require_exact_semantic_stage_count():
    records = [
        {
            "event_type": "http.exchange",
            "observed_at": "2026-01-01T00:00:01Z",
            "correlation": {"request_id": "request-1"},
            "payload": {
                "method": "POST",
                "path": "/api/v1/generations",
                "duration_ms": 500,
            },
        }
    ]
    with pytest.raises(timings.TimingEvidenceError, match="does not match"):
        timings._provider_calls(records, "request-1", ["INTENT", "CONTEXT"])


def test_runtime_step_duration_uses_matching_job_identity():
    records = [
        {
            "event_type": "runtime.step.started",
            "observed_at": "2026-01-01T00:00:00Z",
            "correlation": {"runtime_job_id": "job-1", "agent_execution_id": "exec-1"},
            "payload": {"executor_kind": "LOCAL_SKILL"},
        },
        {
            "event_type": "runtime.step.completed",
            "observed_at": "2026-01-01T00:00:00.750Z",
            "correlation": {"runtime_job_id": "job-1", "agent_execution_id": "exec-1"},
            "payload": {
                "step_input": {
                    "executable_step": {
                        "executor_kind": "LOCAL_SKILL",
                        "required_capability": "FINANCE.COST_ALLOCATION.RUN",
                        "compiled_step_key": "E1",
                    }
                }
            },
        },
    ]
    result = timings._runtime_steps(records)
    assert result == [
        {
            "runtime_job_id": "job-1",
            "agent_execution_id": "exec-1",
            "executor_kind": "LOCAL_SKILL",
            "required_capability": "FINANCE.COST_ALLOCATION.RUN",
            "compiled_step_key": "E1",
            "start_at": "2026-01-01T00:00:00.000Z",
            "end_at": "2026-01-01T00:00:00.750Z",
            "duration_ms": 750.0,
        }
    ]


def test_live_report_must_be_pass(tmp_path):
    report = tmp_path / "live.json"
    report.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
    with pytest.raises(timings.TimingEvidenceError, match="requires a PASS"):
        timings.analyze_live_timings(report)
