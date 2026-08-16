#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_protected_live_rag_postgres_smoke import (  # noqa: E402
    DEFAULT_PROFILE as POSTGRES_DEFAULT_PROFILE,
    HttpRequester,
    SCORE_CALIBRATION_SCHEMA_VERSION,
    SERVICE_ID,
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    SMOKE_PROFILE_ENV as POSTGRES_SMOKE_PROFILE_ENV,
    assert_protected_live_rag_postgres_evidence_redacted,
    run_protected_live_rag_postgres_smoke,
)


SMOKE_ENV = "NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_SMOKE"
SMOKE_PROFILE_ENV = "NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_SMOKE_PROFILE"
SAMPLE_COUNT_ENV = "NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_COUNT"
DEFAULT_PROFILE = POSTGRES_DEFAULT_PROFILE
DEFAULT_SAMPLE_COUNT = 3
MAX_SAMPLE_COUNT = 10
SCHEMA_VERSION = "protected_live_rag_score_sample_smoke.v1"
SAMPLE_SCHEMA_VERSION = "protected_live_rag_score_sample.v1"

LiveRagPostgresSmokeRunner = Callable[..., dict[str, object]]


def run_protected_live_rag_score_sample_smoke(
    environ: dict[str, str] | None = None,
    *,
    runner: LiveRagPostgresSmokeRunner = run_protected_live_rag_postgres_smoke,
    requester: HttpRequester | None = None,
    trace_id_factory: Callable[[int], str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "service_id": SERVICE_ID,
            "profile": profile,
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for score sample collection.",
            profile=profile,
        )
    try:
        sample_count = _sample_count_from_env(env)
    except ValueError as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)

    trace_ids = [
        _sample_trace_id(index, trace_id_factory=trace_id_factory)
        for index in range(sample_count)
    ]
    samples: list[dict[str, object]] = []
    sample_summaries: list[dict[str, object]] = []
    for index, trace_id in enumerate(trace_ids):
        inner_env = {
            **env,
            POSTGRES_SMOKE_ENV: "1",
            POSTGRES_SMOKE_PROFILE_ENV: profile,
        }
        try:
            inner_evidence = runner(
                environ=inner_env,
                requester=requester,
                trace_id=trace_id,
            )
        except Exception as exc:
            failure = _failure(
                "execution_failed",
                exc.__class__.__name__,
                profile=profile,
                sample_summaries=[
                    {
                        "sample_index": index,
                        "trace_id": trace_id,
                        "status": "FAIL",
                        "failure_code": exc.__class__.__name__,
                    }
                ],
            )
            assert_protected_live_rag_score_sample_evidence_redacted(failure, env)
            return failure

        sample_summaries.append(_inner_status_summary(index, trace_id, inner_evidence))
        if inner_evidence.get("status") != "PASS":
            failure = _failure(
                "sample_collection_failed",
                "Nested protected live RAG PostgreSQL smoke did not pass.",
                profile=profile,
                sample_summaries=sample_summaries,
            )
            assert_protected_live_rag_score_sample_evidence_redacted(failure, env)
            return failure
        samples.append(_score_sample_from_inner_evidence(index, trace_id, inner_evidence))

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "sample_count_requested": sample_count,
        "sample_count_collected": len(samples),
        "trace_ids": trace_ids,
        "samples": samples,
        "summary": summarize_score_samples(samples),
        "checks": _checks(sample_count=sample_count, samples=samples),
    }
    if not all(evidence["checks"].values()):
        failure = _failure(
            "sample_checks_failed",
            "Protected live RAG score sample smoke checks failed.",
            profile=profile,
            sample_summaries=sample_summaries,
            summary=evidence["summary"],
            checks=evidence["checks"],
        )
        assert_protected_live_rag_score_sample_evidence_redacted(failure, env)
        return failure
    assert_protected_live_rag_score_sample_evidence_redacted(evidence, env)
    return evidence


def summarize_score_samples(samples: list[dict[str, object]]) -> dict[str, object]:
    statuses = Counter(_safe_string(sample.get("observed_status")) for sample in samples)
    buckets = Counter(
        _safe_string(sample.get("default_confidence_bucket")) for sample in samples
    )
    actions = Counter(_safe_string(sample.get("calibration_action")) for sample in samples)
    policies = Counter(_safe_string(sample.get("retrieval_policy_id")) for sample in samples)
    margins = [
        float(sample["score_margin_to_default_threshold"])
        for sample in samples
        if isinstance(sample.get("score_margin_to_default_threshold"), int | float)
    ]
    return {
        "total": len(samples),
        "by_observed_status": dict(sorted(statuses.items())),
        "by_default_confidence_bucket": dict(sorted(buckets.items())),
        "by_calibration_action": dict(sorted(actions.items())),
        "by_policy": dict(sorted(policies.items())),
        "threshold_override_count": sum(
            1 for sample in samples if sample.get("threshold_override_used") is True
        ),
        "would_pass_default_threshold": sum(
            1 for sample in samples if sample.get("would_pass_default_threshold") is True
        ),
        "score_margin_to_default_threshold": _margin_range(margins),
    }


def assert_protected_live_rag_score_sample_evidence_redacted(
    evidence: object,
    env: dict[str, str],
) -> None:
    assert_protected_live_rag_postgres_evidence_redacted(evidence, env)


def _sample_count_from_env(env: dict[str, str]) -> int:
    raw_value = env.get(SAMPLE_COUNT_ENV)
    if raw_value is None or raw_value.strip() == "":
        return DEFAULT_SAMPLE_COUNT
    try:
        sample_count = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{SAMPLE_COUNT_ENV} must be an integer.") from exc
    if sample_count < 1:
        raise ValueError(f"{SAMPLE_COUNT_ENV} must be at least 1.")
    if sample_count > MAX_SAMPLE_COUNT:
        raise ValueError(f"{SAMPLE_COUNT_ENV} must be at most {MAX_SAMPLE_COUNT}.")
    return sample_count


def _sample_trace_id(
    sample_index: int,
    *,
    trace_id_factory: Callable[[int], str] | None,
) -> str:
    trace_id = (
        trace_id_factory(sample_index)
        if trace_id_factory is not None
        else f"{0x30200000000000000000000000000000 + sample_index:032x}"
    )
    if not isinstance(trace_id, str) or len(trace_id) != 32:
        raise ValueError("score sample trace id must be a 32-character hex string")
    try:
        int(trace_id, 16)
    except ValueError as exc:
        raise ValueError("score sample trace id must be hexadecimal") from exc
    return trace_id


def _score_sample_from_inner_evidence(
    sample_index: int,
    trace_id: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    rag_evidence = evidence.get("rag_evidence")
    rag = rag_evidence if isinstance(rag_evidence, dict) else {}
    retrieval_value = rag.get("retrieval")
    retrieval = retrieval_value if isinstance(retrieval_value, dict) else {}
    score_value = evidence.get("score_calibration")
    score = score_value if isinstance(score_value, dict) else {}
    db_value = evidence.get("db_observations")
    db = db_value if isinstance(db_value, dict) else {}
    return {
        "sample_schema_version": SAMPLE_SCHEMA_VERSION,
        "sample_index": sample_index,
        "trace_id": trace_id,
        "request_id": _safe_string(rag.get("request_id")),
        "retrieval_package_id": _safe_string(retrieval.get("retrieval_package_id")),
        "retrieval_policy_id": _safe_string(score.get("quality_policy_id")),
        "observed_status": _safe_string(score.get("observed_status")),
        "observed_confidence_bucket": _safe_string(
            score.get("observed_confidence_bucket")
        ),
        "default_confidence_bucket": _safe_string(score.get("default_confidence_bucket")),
        "best_score": _safe_float(score.get("best_score")),
        "evidence_count": _safe_int(score.get("evidence_count")),
        "observed_low_confidence_threshold": _safe_float(
            score.get("observed_low_confidence_threshold")
        ),
        "default_low_confidence_threshold": _safe_float(
            score.get("default_low_confidence_threshold")
        ),
        "threshold_override_used": bool(score.get("threshold_override_used") is True),
        "threshold_override_direction": _safe_string(
            score.get("threshold_override_direction")
        ),
        "would_pass_default_threshold": bool(
            score.get("would_pass_default_threshold") is True
        ),
        "score_margin_to_observed_threshold": _safe_float(
            score.get("score_margin_to_observed_threshold")
        ),
        "score_margin_to_default_threshold": _safe_float(
            score.get("score_margin_to_default_threshold")
        ),
        "calibration_action": _safe_string(score.get("calibration_action")),
        "rerank_state": _safe_string(retrieval.get("rerank_state")),
        "ranker_mix": _safe_string(retrieval.get("ranker_mix")),
        "db_retrieval_status": _safe_string(db.get("retrieval_status")),
        "db_retrieval_evidence_count": _safe_int(db.get("retrieval_evidence_count")),
        "checkpoint_schema_version": _safe_string(
            score.get("checkpoint_schema_version")
        ),
    }


def _checks(*, sample_count: int, samples: list[dict[str, object]]) -> dict[str, bool]:
    return {
        "requested_samples_collected": len(samples) == sample_count,
        "sample_schema_version_recorded": all(
            sample.get("sample_schema_version") == SAMPLE_SCHEMA_VERSION
            for sample in samples
        ),
        "score_calibration_checkpoint_recorded": all(
            sample.get("checkpoint_schema_version") == SCORE_CALIBRATION_SCHEMA_VERSION
            for sample in samples
        ),
        "retrieval_package_ids_recorded": all(
            sample.get("retrieval_package_id") != "UNKNOWN" for sample in samples
        ),
        "trace_ids_unique": len({sample.get("trace_id") for sample in samples})
        == len(samples),
    }


def _inner_status_summary(
    sample_index: int,
    trace_id: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    summary = {
        "sample_index": sample_index,
        "trace_id": trace_id,
        "status": _safe_string(evidence.get("status")),
    }
    failure_code = evidence.get("failure_code")
    if isinstance(failure_code, str) and failure_code:
        summary["failure_code"] = failure_code
    diagnostics = evidence.get("diagnostics")
    if isinstance(diagnostics, dict):
        stage = diagnostics.get("stage")
        if isinstance(stage, str) and stage:
            summary["stage"] = stage
    return summary


def _margin_range(margins: list[float]) -> dict[str, float | None]:
    if not margins:
        return {"min": None, "max": None}
    return {"min": round(min(margins), 6), "max": round(max(margins), 6)}


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_string(value: object, *, default: str = "UNKNOWN") -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    sample_summaries: list[dict[str, object]] | None = None,
    summary: dict[str, object] | None = None,
    checks: dict[str, bool] | None = None,
) -> dict[str, object]:
    failure: dict[str, object] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if sample_summaries is not None:
        failure["sample_summaries"] = sample_summaries
    if summary is not None:
        failure["summary"] = summary
    if checks is not None:
        failure["checks"] = checks
    return failure


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"protected_live_rag_score_sample_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        summary = evidence["summary"]
        if not isinstance(summary, dict):
            summary = {}
        return (
            "protected_live_rag_score_sample_smoke=pass "
            f"service={evidence['service_id']} "
            f"profile={evidence['profile']} "
            f"samples={evidence['sample_count_collected']} "
            f"override_count={summary.get('threshold_override_count', 0)} "
            f"default_pass={summary.get('would_pass_default_threshold', 0)}"
        )
    return (
        "protected_live_rag_score_sample_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"profile={evidence.get('profile')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect protected live RAG score-calibration samples."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    evidence = run_protected_live_rag_score_sample_smoke()
    if args.output:
        serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
