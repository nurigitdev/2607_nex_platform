#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "quality"):
    sys.path.insert(0, str(path))

from check_model_calibration_dataset import (  # noqa: E402
    DEFAULT_V2_PATH,
    admit_calibration_dataset_files,
)
from nex_runtime import (  # noqa: E402
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import (  # noqa: E402
    semantic_sha256_hash_ref,
    sha256_text,
)

SCHEMA_VERSION = "gb2_s20n_single_signal_calibration.v1"
EXPECTED_SOURCE_SCHEMA_VERSION = "gb2_s20ma_provider_numeric_repeatability.v1"
DEFAULT_REPEATABILITY_EVIDENCE_PATH = (
    ROOT / "reports/live/gb2_ca00_s20ma_numeric_repeatability_rerun.json"
)
DEFAULT_CONSTRAINTS = BinaryCalibrationConstraints()
CALIBRATION_PARTITION = "CALIBRATION"
HOLDOUT_PARTITION = "HOLDOUT"
REQUIRED_SOURCE_CHECKS = frozenset(
    {
        "model_revision_stable",
        "deployment_identity_stable",
        "repeat_count_complete",
        "pair_coverage_complete",
        "observation_count_complete",
        "scores_finite",
        "scores_bounded",
        "tolerance_within_hard_cap",
        "cross_label_rank_stable",
        "same_label_non_near_rank_stable",
    }
)


def run_gb2_s20n_single_signal_calibration(
    *,
    repeatability_evidence_path: Path = DEFAULT_REPEATABILITY_EVIDENCE_PATH,
    dataset_path: Path = DEFAULT_V2_PATH,
) -> dict[str, Any]:
    try:
        admitted = admit_calibration_dataset_files(v2_path=dataset_path)
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        source_text = repeatability_evidence_path.read_text(encoding="utf-8")
        source = json.loads(source_text)
        expected_pairs = _dataset_pair_manifest(dataset)
        source_profile = _validate_source_header(source, admitted["v2"])
        observations = _validate_observation_envelope(
            source,
            expected_pairs=expected_pairs,
            source_profile=source_profile,
        )

        calibration_samples = _collapse_partition(
            observations,
            expected_pairs=expected_pairs,
            partition=CALIBRATION_PARTITION,
            repeat_count=source_profile["repeat_count"],
        )
        fit = evaluate_binary_score_calibration(
            calibration_samples,
            dataset_id=f"{admitted['v2']['dataset_id']}:calibration",
            constraints=DEFAULT_CONSTRAINTS,
        )
        if fit["status"] not in {"PASSED", "NO_ACCEPTABLE_THRESHOLD"}:
            raise ValueError("Calibration partition cannot produce a decision.")

        selected_threshold = fit.get("selected_threshold")
        diagnostic_threshold = selected_threshold
        if diagnostic_threshold is None:
            best_effort = fit.get("best_effort_metrics")
            if not isinstance(best_effort, Mapping):
                raise ValueError("Calibration best-effort metrics are unavailable.")
            diagnostic_threshold = best_effort.get("threshold")
        calibration_evaluation = evaluate_binary_score_threshold(
            calibration_samples,
            dataset_id=f"{admitted['v2']['dataset_id']}:calibration",
            threshold=diagnostic_threshold,
            constraints=DEFAULT_CONSTRAINTS,
        )
        freeze_record = {
            "status": (
                "FROZEN" if fit["status"] == "PASSED" else "NO_ACCEPTABLE_THRESHOLD"
            ),
            "threshold": selected_threshold,
            "diagnostic_threshold": diagnostic_threshold,
            "selection_partition": CALIBRATION_PARTITION,
            "selection_sample_count": len(calibration_samples),
            "selection_sample_sha256": fit["dataset_sha256"],
            "constraints": {
                "maximum_false_ready_rate": (
                    DEFAULT_CONSTRAINTS.maximum_false_ready_rate
                ),
                "minimum_ready_recall": DEFAULT_CONSTRAINTS.minimum_ready_recall,
            },
            "model_binding": source_profile["binding"],
            "dataset_id": admitted["v2"]["dataset_id"],
            "dataset_sha256": admitted["v2"]["dataset_sha256"],
        }
        freeze_record["freeze_hash"] = semantic_sha256_hash_ref(freeze_record)

        holdout: dict[str, Any]
        if selected_threshold is None:
            decision = "MULTI_SIGNAL_REQUIRED"
            decision_reason = "calibration_threshold_unacceptable"
            holdout = {
                "status": "SEALED_NOT_OPENED",
                "reason": decision_reason,
                "expected_sample_count": 40,
                "threshold_reselected": False,
            }
        else:
            holdout_samples = _collapse_partition(
                observations,
                expected_pairs=expected_pairs,
                partition=HOLDOUT_PARTITION,
                repeat_count=source_profile["repeat_count"],
            )
            holdout_evaluation = evaluate_binary_score_threshold(
                holdout_samples,
                dataset_id=f"{admitted['v2']['dataset_id']}:holdout",
                threshold=selected_threshold,
                constraints=DEFAULT_CONSTRAINTS,
            )
            admitted_single_signal = holdout_evaluation["status"] == "PASSED"
            decision = (
                "SINGLE_SIGNAL_ADMITTED"
                if admitted_single_signal
                else "MULTI_SIGNAL_REQUIRED"
            )
            decision_reason = (
                "frozen_threshold_passed_holdout"
                if admitted_single_signal
                else "frozen_threshold_failed_holdout"
            )
            holdout = {
                "status": "EVALUATED",
                "threshold_freeze_hash": freeze_record["freeze_hash"],
                "threshold_reselected": False,
                "evaluation": holdout_evaluation,
            }

        checks = {
            "repeatability_evidence_admitted": True,
            "dataset_binding_matches": True,
            "calibration_partition_complete": len(calibration_samples) == 80,
            "threshold_selection_used_calibration_only": True,
            "threshold_frozen_before_holdout": True,
            "holdout_threshold_not_reselected": not holdout["threshold_reselected"],
            "decision_recorded": decision
            in {"SINGLE_SIGNAL_ADMITTED", "MULTI_SIGNAL_REQUIRED"},
        }
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "evidence_generated_at": _utc_now(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "decision": decision,
            "decision_reason": decision_reason,
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "source_evidence": {
                "schema_version": source.get("evidence_schema_version"),
                "sha256": sha256_text(source_text),
                "candidate_profile_id": source_profile["profile_id"],
            },
            "provider_binding": source_profile["binding"],
            "dataset_binding": {
                "dataset_id": admitted["v2"]["dataset_id"],
                "dataset_sha256": admitted["v2"]["dataset_sha256"],
                "calibration_pair_count": 80,
                "holdout_pair_count": 40,
            },
            "constraints": {
                "maximum_false_ready_rate": (
                    DEFAULT_CONSTRAINTS.maximum_false_ready_rate
                ),
                "minimum_ready_recall": DEFAULT_CONSTRAINTS.minimum_ready_recall,
            },
            "score_aggregation": "MEDIAN_ACROSS_REPEATS",
            "calibration_fit": fit,
            "calibration_threshold_evaluation": calibration_evaluation,
            "threshold_freeze": freeze_record,
            "holdout": holdout,
            "raw_text_persisted": False,
            "provider_endpoint_persisted": False,
            "provider_credential_persisted": False,
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "single_signal_calibration_failed",
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, dataset_path)
    return result


def _validate_source_header(
    source: Mapping[str, Any],
    admitted: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        source.get("evidence_schema_version") != EXPECTED_SOURCE_SCHEMA_VERSION
        or source.get("status") != "PASS"
    ):
        raise ValueError("Repeatability evidence is not admitted.")
    checks = source.get("checks")
    if (
        not isinstance(checks, Mapping)
        or not REQUIRED_SOURCE_CHECKS.issubset(checks)
        or not all(checks.get(name) is True for name in REQUIRED_SOURCE_CHECKS)
    ):
        raise ValueError("Repeatability evidence checks did not pass.")
    profile = source.get("candidate_profile")
    if not isinstance(profile, Mapping) or profile.get("status") != "CANDIDATE":
        raise ValueError("Repeatability candidate profile is unavailable.")
    binding = profile.get("binding")
    measurement = profile.get("measurement")
    policy = profile.get("policy")
    if not all(isinstance(item, Mapping) for item in (binding, measurement, policy)):
        raise ValueError("Repeatability candidate profile is malformed.")
    if binding.get("dataset_id") != admitted.get("dataset_id") or binding.get(
        "dataset_sha256"
    ) != admitted.get("dataset_sha256"):
        raise ValueError("Repeatability dataset binding does not match admission.")
    required_binding = {
        "capability",
        "model_name",
        "model_revision",
        "deployment_id",
        "request_shape",
        "score_semantics",
        "retrieval_policy_id",
        "dataset_id",
        "dataset_sha256",
    }
    if any(not _is_non_empty_string(binding.get(field)) for field in required_binding):
        raise ValueError("Repeatability model binding is incomplete.")
    repeat_count = measurement.get("repeat_count")
    observation_count = measurement.get("observation_count")
    tolerance = policy.get("score_delta_tolerance")
    if (
        type(repeat_count) is not int
        or repeat_count < 2
        or type(observation_count) is not int
        or observation_count != int(admitted["pair_count"]) * repeat_count
        or isinstance(tolerance, bool)
        or not isinstance(tolerance, int | float)
        or not 0.0 <= float(tolerance) <= 0.005
    ):
        raise ValueError("Repeatability measurement policy is invalid.")
    return {
        "profile_id": _required_string(profile.get("profile_id"), "profile_id"),
        "binding": {field: binding[field] for field in sorted(required_binding)},
        "repeat_count": repeat_count,
        "observation_count": observation_count,
        "score_delta_tolerance": float(tolerance),
    }


def _validate_observation_envelope(
    source: Mapping[str, Any],
    *,
    expected_pairs: Mapping[str, Mapping[str, Any]],
    source_profile: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    observations = source.get("score_observations")
    if not isinstance(observations, list):
        raise ValueError("Repeatability observations must be an array.")
    if len(observations) != source_profile["observation_count"]:
        raise ValueError("Repeatability observation count is incomplete.")
    binding = source_profile["binding"]
    repeat_count = int(source_profile["repeat_count"])
    seen: set[tuple[str, int]] = set()
    scores_by_pair: dict[str, list[float]] = {}
    for item in observations:
        if not isinstance(item, Mapping):
            raise ValueError("Repeatability observation must be an object.")
        pair_id = _required_string(item.get("pair_id"), "pair_id")
        expected = expected_pairs.get(pair_id)
        if expected is None:
            raise ValueError("Repeatability observation pair is unknown.")
        repeat_index = item.get("repeat_index")
        score = item.get("score")
        rank = item.get("rank")
        if (
            type(repeat_index) is not int
            or not 1 <= repeat_index <= repeat_count
            or isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(float(score))
            or not 0.0 <= float(score) <= 1.0
            or type(rank) is not int
            or rank < 1
        ):
            raise ValueError("Repeatability observation values are invalid.")
        key = (pair_id, repeat_index)
        if key in seen:
            raise ValueError("Repeatability observation is duplicated.")
        seen.add(key)
        if (
            item.get("case_id") != expected["case_id"]
            or item.get("partition") != expected["partition"]
            or item.get("relevance_grade") != expected["relevance_grade"]
            or item.get("expected_ready") is not expected["expected_ready"]
            or item.get("model_revision") != binding["model_revision"]
            or item.get("deployment_id") != binding["deployment_id"]
        ):
            raise ValueError("Repeatability observation binding drifted.")
        scores_by_pair.setdefault(pair_id, []).append(float(score))
    expected_keys = {
        (pair_id, repeat_index)
        for pair_id in expected_pairs
        for repeat_index in range(1, repeat_count + 1)
    }
    if seen != expected_keys:
        raise ValueError("Repeatability pair/repeat coverage is incomplete.")
    tolerance = float(source_profile["score_delta_tolerance"])
    if any(max(scores) - min(scores) > tolerance for scores in scores_by_pair.values()):
        raise ValueError("Repeatability scores exceed the admitted tolerance.")
    return observations


def _collapse_partition(
    observations: Sequence[Mapping[str, Any]],
    *,
    expected_pairs: Mapping[str, Mapping[str, Any]],
    partition: str,
    repeat_count: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for item in observations:
        if item.get("partition") == partition:
            grouped.setdefault(str(item["pair_id"]), []).append(float(item["score"]))
    expected_ids = {
        pair_id
        for pair_id, metadata in expected_pairs.items()
        if metadata["partition"] == partition
    }
    if set(grouped) != expected_ids or any(
        len(scores) != repeat_count for scores in grouped.values()
    ):
        raise ValueError(f"{partition} partition coverage is incomplete.")
    return [
        {
            "sample_id": pair_id,
            "expected_ready": expected_pairs[pair_id]["expected_ready"],
            "score": statistics.median(grouped[pair_id]),
        }
        for pair_id in sorted(grouped)
    ]


def _dataset_pair_manifest(dataset: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Calibration dataset cases are invalid.")
    manifest: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping) or not isinstance(case.get("documents"), list):
            raise ValueError("Calibration dataset case is invalid.")
        case_id = _required_string(case.get("case_id"), "case_id")
        for document in case["documents"]:
            if not isinstance(document, Mapping):
                raise ValueError("Calibration dataset document is invalid.")
            document_id = _required_string(document.get("document_id"), "document_id")
            pair_id = f"{case_id}:{document_id}"
            manifest[pair_id] = {
                "case_id": case_id,
                "partition": case.get("partition"),
                "relevance_grade": document.get("relevance_grade"),
                "expected_ready": document.get("expected_ready"),
            }
    return manifest


def _assert_redacted(evidence: object, dataset_path: Path) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        dataset = None
    protected: list[str] = []
    if isinstance(dataset, Mapping):
        protected.extend(
            str(value)
            for case in dataset.get("cases", [])
            for value in (
                case.get("query"),
                *(document.get("text") for document in case.get("documents", [])),
            )
            if isinstance(value, str)
        )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("Single-signal calibration evidence contains protected text.")


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _required_string(value: object, field: str) -> str:
    if not _is_non_empty_string(value):
        raise ValueError(f"{field} must be a non-empty string.")
    return str(value).strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        evaluation = result.get("calibration_threshold_evaluation") or {}
        metrics = evaluation.get("metrics") or {}
        return (
            "gb2_s20n_single_signal=pass "
            f"decision={result.get('decision')} "
            f"threshold={result.get('threshold_freeze', {}).get('threshold')} "
            f"false_ready_rate={metrics.get('false_ready_rate')} "
            f"ready_recall={metrics.get('ready_recall')} "
            f"holdout={result.get('holdout', {}).get('status')}"
        )
    return (
        "gb2_s20n_single_signal=fail "
        f"reason={result.get('failure_code', 'execution')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repeatability-evidence",
        type=Path,
        default=DEFAULT_REPEATABILITY_EVIDENCE_PATH,
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_V2_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20n_single_signal_calibration(
        repeatability_evidence_path=args.repeatability_evidence,
        dataset_path=args.dataset,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
