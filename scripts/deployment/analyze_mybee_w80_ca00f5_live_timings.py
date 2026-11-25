#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIVE_REPORT = (
    ROOT / "reports/deployment/mybee-w80-ca00f5c-split-live-journeys.json"
)
DEFAULT_OUTPUT = ROOT / "reports/deployment/mybee-w80-ca00f5c-stage-timings.json"
SCHEMA_VERSION = "mybee_w80_ca00f5_stage_timings.v1"


class TimingEvidenceError(RuntimeError):
    pass


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise TimingEvidenceError("timing evidence timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _milliseconds(start: datetime, end: datetime) -> float:
    if end < start:
        raise TimingEvidenceError("timing evidence is not monotonic")
    return round((end - start).total_seconds() * 1000, 3)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise TimingEvidenceError(f"missing timing evidence: {path.name}")
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _load_captures(session_root: Path, manifest_name: str) -> list[dict[str, Any]]:
    path = session_root / "screens" / manifest_name
    if not path.is_file():
        raise TimingEvidenceError(f"missing screen manifest: {manifest_name}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    captures = list(manifest.get("captures", ()))
    if not captures:
        raise TimingEvidenceError(f"empty screen manifest: {manifest_name}")
    return captures


def _capture_time(capture: dict[str, Any]) -> datetime:
    return _timestamp(str(capture["captured_at"]))


def _chat_exchange(
    records: list[dict[str, Any]], interaction_id: str
) -> dict[str, Any]:
    matches = [
        record
        for record in records
        if record.get("event_type") == "http.exchange"
        and record.get("payload", {}).get("method") == "POST"
        and record.get("payload", {}).get("path") == "/api/v1/chat/interactions"
        and record.get("payload", {})
        .get("response_body", {})
        .get("interaction_id")
        == interaction_id
    ]
    if len(matches) != 1:
        raise TimingEvidenceError(
            f"expected one chat exchange for interaction {interaction_id}"
        )
    return matches[0]


def _exchange_window(record: dict[str, Any]) -> tuple[datetime, datetime, float]:
    end = _timestamp(str(record["observed_at"]))
    duration_ms = float(record["payload"]["duration_ms"])
    return end - timedelta(milliseconds=duration_ms), end, round(duration_ms, 3)


def _stage(name: str, start: datetime, end: datetime, evidence_kind: str) -> dict[str, Any]:
    return {
        "name": name,
        "start_at": _iso(start),
        "end_at": _iso(end),
        "duration_ms": _milliseconds(start, end),
        "evidence_kind": evidence_kind,
    }


def _provider_calls(
    records: list[dict[str, Any]], request_id: str, semantic_stages: list[str]
) -> list[dict[str, Any]]:
    calls = [
        record
        for record in records
        if record.get("event_type") == "http.exchange"
        and record.get("payload", {}).get("method") == "POST"
        and record.get("payload", {}).get("path") == "/api/v1/generations"
        and record.get("correlation", {}).get("request_id") == request_id
    ]
    if len(calls) != len(semantic_stages):
        raise TimingEvidenceError(
            f"provider call count does not match semantic stages for {request_id}"
        )
    result = []
    for stage_name, call in zip(semantic_stages, calls, strict=True):
        start, end, duration_ms = _exchange_window(call)
        result.append(
            {
                "semantic_stage": stage_name,
                "start_at": _iso(start),
                "end_at": _iso(end),
                "duration_ms": duration_ms,
            }
        )
    return result


def _runtime_steps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    starts: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []
    for record in records:
        job_id = str(record.get("correlation", {}).get("runtime_job_id") or "")
        if not job_id:
            continue
        if record.get("event_type") == "runtime.step.started":
            starts[job_id] = record
        elif record.get("event_type") == "runtime.step.completed":
            completed.append(record)
    result = []
    for record in completed:
        job_id = str(record["correlation"]["runtime_job_id"])
        start_record = starts.get(job_id)
        if start_record is None:
            raise TimingEvidenceError(f"runtime step start missing for {job_id}")
        start = _timestamp(str(start_record["observed_at"]))
        end = _timestamp(str(record["observed_at"]))
        executable_step = record.get("payload", {}).get("step_input", {}).get(
            "executable_step", {}
        )
        result.append(
            {
                "runtime_job_id": job_id,
                "agent_execution_id": record.get("correlation", {}).get(
                    "agent_execution_id"
                ),
                "executor_kind": executable_step.get("executor_kind")
                or start_record.get("payload", {}).get("executor_kind"),
                "required_capability": executable_step.get("required_capability"),
                "compiled_step_key": executable_step.get("compiled_step_key"),
                "start_at": _iso(start),
                "end_at": _iso(end),
                "duration_ms": _milliseconds(start, end),
            }
        )
    return result


def analyze_live_timings(live_report_path: Path) -> dict[str, Any]:
    live_report = json.loads(live_report_path.read_text(encoding="utf-8"))
    if live_report.get("status") != "PASS":
        raise TimingEvidenceError("timing analysis requires a PASS live report")
    finalization = live_report.get("finalization_evidence") or {}
    if finalization.get("status") != "PASS":
        raise TimingEvidenceError("timing analysis requires PASS diagnostic evidence")
    session_root = ROOT / str(finalization["relative_path"])

    journal = _load_captures(
        session_root, "mybee-m1-w80-journal-screen-manifest.json"
    )
    allocation = _load_captures(
        session_root, "mybee-m1-w80-allocation-screen-manifest.json"
    )
    journal_recovery = _load_captures(
        session_root, "mybee-m1-w80-journal-recovery-screen-manifest.json"
    )
    allocation_recovery = _load_captures(
        session_root, "mybee-m1-w80-allocation-recovery-screen-manifest.json"
    )
    approvals = [item for item in journal if item["expected_state"] == "APPROVAL_RECORDED"]
    if len(approvals) != 3:
        raise TimingEvidenceError("journal timing requires exactly three approval captures")

    journal_interaction = str(journal[1]["interaction_id"])
    allocation_interaction = str(allocation[1]["interaction_id"])
    ae_http = _read_jsonl(session_root / "nex-ae-api--http-api--1.jsonl")
    mo_http = _read_jsonl(session_root / "nex-mo--http-api--1.jsonl")
    runtime = _read_jsonl(session_root / "nex-ae-api--agent-runtime-worker--1.jsonl")
    journal_chat = _chat_exchange(ae_http, journal_interaction)
    allocation_chat = _chat_exchange(ae_http, allocation_interaction)
    journal_start, journal_end, journal_api_ms = _exchange_window(journal_chat)
    allocation_start, _allocation_end, allocation_api_ms = _exchange_window(
        allocation_chat
    )

    journal_admitted = _capture_time(journal[1])
    approval_times = [_capture_time(item) for item in approvals]
    journal_rendered = _capture_time(journal[-1])
    allocation_admitted = _capture_time(allocation[1])
    allocation_rendered = _capture_time(allocation[-1])
    journal_recovered = _capture_time(journal_recovery[0])
    allocation_recovered = _capture_time(allocation_recovery[0])

    journal_request_id = str(journal_chat["payload"]["response_body"]["request_id"])
    allocation_request_id = str(
        allocation_chat["payload"]["response_body"]["request_id"]
    )
    journal_stage_names = [
        str(item["semantic_stage"])
        for item in journal_chat["payload"]["response_body"]["generation"]
        ["semantic_planning"]["stages"]
    ]
    allocation_stage_names = [
        str(item["semantic_stage"])
        for item in allocation_chat["payload"]["response_body"]["generation"]
        ["semantic_planning"]["stages"]
    ]
    provider_calls = {
        "journal_ia_semantic": _provider_calls(
            mo_http, journal_request_id, journal_stage_names
        ),
        "allocation_ia_semantic": _provider_calls(
            mo_http, allocation_request_id, allocation_stage_names
        ),
    }
    pa_calls = [
        record
        for record in mo_http
        if record.get("event_type") == "http.exchange"
        and record.get("payload", {}).get("method") == "POST"
        and record.get("payload", {}).get("path") == "/api/v1/generations"
        and str(record.get("correlation", {}).get("request_id", "")).startswith(
            "claim-handoff:"
        )
        and journal_end <= _timestamp(str(record["observed_at"])) <= approval_times[0]
    ]
    provider_calls["journal_pa_planning"] = [
        {
            "semantic_stage": "ROLE_SCOPED_PLAN",
            "start_at": _iso(_exchange_window(call)[0]),
            "end_at": _iso(_exchange_window(call)[1]),
            "duration_ms": _exchange_window(call)[2],
        }
        for call in pa_calls
    ]
    provider_summary = {
        "journal_ia_semantic": {
            "call_count": len(provider_calls["journal_ia_semantic"]),
            "total_duration_ms": round(
                sum(
                    item["duration_ms"]
                    for item in provider_calls["journal_ia_semantic"]
                ),
                3,
            ),
        },
        "journal_pa_planning": {
            "call_count": len(provider_calls["journal_pa_planning"]),
            "total_duration_ms": round(
                sum(
                    item["duration_ms"]
                    for item in provider_calls["journal_pa_planning"]
                ),
                3,
            ),
        },
        "allocation_ia_semantic": {
            "call_count": len(provider_calls["allocation_ia_semantic"]),
            "total_duration_ms": round(
                sum(
                    item["duration_ms"]
                    for item in provider_calls["allocation_ia_semantic"]
                ),
                3,
            ),
        },
    }
    provider_summary["journal_ia_semantic"]["chat_api_share_percent"] = round(
        provider_summary["journal_ia_semantic"]["total_duration_ms"]
        / journal_api_ms
        * 100,
        2,
    )
    provider_summary["allocation_ia_semantic"]["chat_api_share_percent"] = round(
        provider_summary["allocation_ia_semantic"]["total_duration_ms"]
        / allocation_api_ms
        * 100,
        2,
    )

    runtime_steps = _runtime_steps(runtime)
    allocation_planning = allocation_chat["payload"]["response_body"]["generation"][
        "semantic_planning"
    ]
    allocation_execution_id = allocation_planning["agent_execution_id"]
    allocation_steps = [
        item
        for item in runtime_steps
        if item["agent_execution_id"] == allocation_execution_id
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": _iso(datetime.now(UTC)),
        "source_live_report": live_report_path.relative_to(ROOT).as_posix(),
        "evidence_session_id": finalization["session_id"],
        "evidence_session_path": finalization["relative_path"],
        "journeys": {
            "journal": {
                "interaction_id": journal_interaction,
                "chat_api_duration_ms": journal_api_ms,
                "request_to_result_ms": _milliseconds(journal_start, journal_rendered),
                "workspace_ready_to_result_ms": _milliseconds(
                    _capture_time(journal[0]), journal_rendered
                ),
                "stages": [
                    _stage("IA_SEMANTIC_ADMISSION", journal_start, journal_admitted, "API_AND_SCREEN"),
                    _stage("DELEGATION_PA_PLANNING_AND_BUSINESS_FORMAL_STAGE_1", journal_admitted, approval_times[0], "SCREEN"),
                    _stage("BUSINESS_FORMAL_STAGE_2", approval_times[0], approval_times[1], "SCREEN"),
                    _stage("NSL_WRITE_APPROVAL", approval_times[1], approval_times[2], "SCREEN"),
                    _stage("COMMIT_FINALIZATION_AND_IA_PROJECTION", approval_times[2], journal_rendered, "SCREEN"),
                ],
            },
            "allocation": {
                "interaction_id": allocation_interaction,
                "chat_api_duration_ms": allocation_api_ms,
                "request_to_result_ms": _milliseconds(
                    allocation_start, allocation_rendered
                ),
                "workspace_ready_to_result_ms": _milliseconds(
                    _capture_time(allocation[0]), allocation_rendered
                ),
                "stages": [
                    _stage("IA_SEMANTIC_ADMISSION", allocation_start, allocation_admitted, "API_AND_SCREEN"),
                    _stage("PRODUCT_EXECUTION_AND_RESULT_PROJECTION", allocation_admitted, allocation_rendered, "SCREEN"),
                ],
                "runtime_steps": allocation_steps,
            },
        },
        "provider_calls": provider_calls,
        "provider_summary": provider_summary,
        "runtime_steps": runtime_steps,
        "restart_recovery": {
            "last_result_to_first_recovered_ms": _milliseconds(
                allocation_rendered, journal_recovered
            ),
            "first_to_second_recovered_ms": _milliseconds(
                journal_recovered, allocation_recovered
            ),
            "last_result_to_both_recovered_ms": _milliseconds(
                allocation_rendered, allocation_recovered
            ),
            "measurement_note": (
                "Observed upper bound from the last pre-restart result screen; "
                "it includes restart orchestration, readiness, login, and rendering."
            ),
        },
        "measurement_notes": [
            "Screen intervals include browser polling and rendering overhead.",
            "HTTP duration_ms measures the service exchange only.",
            "Provider durations are serial remote generation calls grouped by request identity.",
            "This is one acceptance run and is evidence, not an SLO percentile.",
        ],
        "raw_prompt_included": False,
        "secret_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze W80 split live-journey stage timings."
    )
    parser.add_argument("--live-report", type=Path, default=DEFAULT_LIVE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = analyze_live_timings(args.live_report.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.summary:
        journal = result["journeys"]["journal"]["request_to_result_ms"] / 1000
        allocation = result["journeys"]["allocation"]["request_to_result_ms"] / 1000
        print(
            f"mybee_w80_timings=pass journal_seconds={journal:.3f} "
            f"allocation_seconds={allocation:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
