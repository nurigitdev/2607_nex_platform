#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_s20qe_v3_calibration_collection as s20qe
import run_gb2_s20qi_candidate_relevance_signal_expansion as s20qi
from check_model_calibration_dataset import DEFAULT_V3_PATH
from nex_cx.retrieval_calibration_policy_audit import (
    CalibrationPolicyAuditError,
    audit_calibration_dataset_and_package_policy,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_expanded_candidate_relevance_calibration_samples,
)

SCHEMA_VERSION = "gb2_s20ql_calibration_policy_audit.v1"
SMOKE_ENV = "NEX_GB2_S20QL_CALIBRATION_POLICY_AUDIT"
HISTORICAL_PATH_ENV = "NEX_GB2_S20QL_HISTORICAL_EVIDENCE_PATH"
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
)

AuditExecutor = Callable[..., tuple[Mapping[str, Any], Mapping[str, Any]]]


def run_gb2_s20ql_calibration_policy_audit(
    environ: Mapping[str, str] | None = None,
    *,
    requester: s20qe.HttpRequester | None = None,
    executor: AuditExecutor | None = None,
    dataset_path: Path = DEFAULT_V3_PATH,
    repeatability_path: Path = s20qi.s20qg.DEFAULT_REPEATABILITY_PATH,
    revision_path: Path = s20qi.s20qg.DEFAULT_REVISION_PATH,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        historical = _read_json(_required_path(env, HISTORICAL_PATH_ENV))
        execute = executor or _execute_live_source
        current, source = execute(
            env,
            requester=requester,
            repeatability_path=repeatability_path,
            revision_path=revision_path,
        )
        if current.get("status") != "PASS" or source.get("status") != "PASS":
            raise CalibrationPolicyAuditError("S20QL_LIVE_SOURCE_NOT_ADMITTED")
        audit = _audit_from_execution(
            dataset_path=dataset_path,
            source=source,
            current=current,
            historical=historical,
        )
        source_counts = _mapping(current.get("source_collection"))
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": "nex-cx",
            "profile": "test",
            "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
            "binding": current.get("binding"),
            "source_collection": dict(source_counts),
            "provider_request_counts": current.get("provider_request_counts"),
            "persistence": current.get("persistence"),
            "checks": current.get("checks"),
            "audit": audit,
        }
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        CalibrationPolicyAuditError,
    ) as exc:
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": getattr(exc, "error_code", "S20QL_EXECUTION_FAILED"),
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, env)
    return result


def _execute_live_source(
    env: Mapping[str, str],
    *,
    requester: s20qe.HttpRequester | None,
    repeatability_path: Path,
    revision_path: Path,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    captured: dict[str, Mapping[str, Any]] = {}

    def collector(
        collector_env: Mapping[str, str],
        *,
        requester: s20qe.HttpRequester | None = None,
    ) -> dict[str, Any]:
        source = s20qe.run_gb2_s20qe_v3_calibration_collection(
            collector_env,
            requester=requester,
        )
        captured["source"] = source
        return source

    current = s20qi.run_gb2_s20qi_candidate_relevance_signal_expansion(
        {**env, s20qi.SMOKE_ENV: "1"},
        requester=requester,
        collector=collector,
        repeatability_path=repeatability_path,
        revision_path=revision_path,
    )
    source = captured.get("source")
    if source is None:
        raise CalibrationPolicyAuditError("S20QL_LIVE_SOURCE_MISSING")
    return current, source


def _audit_from_execution(
    *,
    dataset_path: Path,
    source: Mapping[str, Any],
    current: Mapping[str, Any],
    historical: Mapping[str, Any],
) -> dict[str, Any]:
    dataset = s20qe._load_dataset(dataset_path)
    calibration_cases = [
        dict(value)
        for value in dataset["cases"]
        if isinstance(value, Mapping) and value.get("partition") == "CALIBRATION"
    ]
    runs = _mapping(source.get("repeat_collection")).get("runs")
    if not isinstance(runs, list) or not runs:
        raise CalibrationPolicyAuditError("S20QL_BASELINE_RUN_MISSING")
    observations = _mapping(runs[0]).get("candidate_observations")
    if not isinstance(observations, list):
        raise CalibrationPolicyAuditError("S20QL_BASELINE_OBSERVATIONS_MISSING")
    samples = build_expanded_candidate_relevance_calibration_samples(observations)
    provenance = _mapping(current.get("provenance"))
    calibration = _mapping(current.get("candidate_relevance_calibration"))
    repeatability = _mapping(calibration.get("repeatability"))
    signal_tolerances = repeatability.get("signal_tolerances")
    if not isinstance(signal_tolerances, Mapping):
        raise CalibrationPolicyAuditError("S20QL_SIGNAL_TOLERANCES_MISSING")
    return audit_calibration_dataset_and_package_policy(
        calibration_cases,
        samples,
        current,
        historical_evidence=historical,
        numeric_tolerance=float(provenance["numeric_tolerance"]),
        signal_tolerances={
            str(key): float(value) for key, value in signal_tolerances.items()
        },
    )


def _required_path(env: Mapping[str, str], key: str) -> Path:
    value = env.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CalibrationPolicyAuditError(f"S20QL_{key}_REQUIRED")
    return Path(value.strip())


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError("S20Q-L evidence must be a JSON object")
    return value


def _assert_redacted(result: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 4 and value in serialized:
            raise ValueError("S20Q-L evidence contains protected data")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20ql_calibration_policy_audit=skipped reason={SMOKE_ENV}"
    if status == "pass":
        decision = _mapping(_mapping(result.get("audit")).get("decision"))
        gap = _mapping(_mapping(result.get("audit")).get("constraint_gap"))
        return (
            "gb2_s20ql_calibration_policy_audit=pass "
            f"decision={decision.get('status')} "
            f"false_ready_excess={gap.get('false_ready_excess')} "
            f"true_ready_deficit={gap.get('true_ready_deficit')}"
        )
    return (
        "gb2_s20ql_calibration_policy_audit=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_V3_PATH)
    parser.add_argument(
        "--repeatability",
        type=Path,
        default=s20qi.s20qg.DEFAULT_REPEATABILITY_PATH,
    )
    parser.add_argument(
        "--revision", type=Path, default=s20qi.s20qg.DEFAULT_REVISION_PATH
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.historical is not None:
        env[HISTORICAL_PATH_ENV] = str(args.historical)
    result = run_gb2_s20ql_calibration_policy_audit(
        env,
        dataset_path=args.dataset,
        repeatability_path=args.repeatability,
        revision_path=args.revision,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
