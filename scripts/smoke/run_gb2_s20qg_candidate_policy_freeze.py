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
from nex_cx.retrieval_confidence_candidate_selection import (
    SELECTABLE_FEATURE_FIELDS,
    select_and_freeze_candidate_policy,
)
from nex_runtime.semantic_hashes import sha256_text

SCHEMA_VERSION = "gb2_s20qg_candidate_policy_freeze.v1"
SMOKE_ENV = "NEX_GB2_S20QG_LIVE_SMOKE"
DEFAULT_REPEATABILITY_PATH = (
    ROOT / "reports/live/gb2_ca00_s20ma_numeric_repeatability_rerun.json"
)
DEFAULT_REVISION_PATH = (
    ROOT / "reports/live/gb2_ca00_s20oa_immutable_reranker_binding.json"
)
REQUIRED_REPEATABILITY_CHECKS = frozenset(
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
REQUIRED_REVISION_CHECKS = frozenset(
    {
        "artifact_evidence_admitted",
        "configured_revision_matches_artifact",
        "deployment_identity_matches",
        "response_revision_matches_artifact",
        "served_name_is_separate_from_revision",
    }
)

Collector = Callable[..., Mapping[str, Any]]
Selector = Callable[..., dict[str, Any]]


def run_gb2_s20qg_candidate_policy_freeze(
    environ: Mapping[str, str] | None = None,
    *,
    requester: s20qe.HttpRequester | None = None,
    collector: Collector = s20qe.run_gb2_s20qe_v3_calibration_collection,
    selector: Selector = select_and_freeze_candidate_policy,
    repeatability_path: Path = DEFAULT_REPEATABILITY_PATH,
    revision_path: Path = DEFAULT_REVISION_PATH,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        repeatability_text, repeatability = _read_json(repeatability_path)
        revision_text, revision = _read_json(revision_path)
        source = collector(
            {**env, s20qe.SMOKE_ENV: "1"},
            requester=requester,
        )
        if source.get("status") != "PASS":
            raise CandidateFreezeError(
                "source_collection_failed",
                {
                    "status": source.get("status"),
                    "failure_code": source.get("failure_code"),
                },
            )
        provenance = _admit_provenance(
            source,
            repeatability=repeatability,
            revision=revision,
            repeatability_sha256=f"sha256:{sha256_text(repeatability_text)}",
            revision_sha256=f"sha256:{sha256_text(revision_text)}",
        )
        diagnostics = _mapping(source.get("candidate_feature_diagnostics"))
        collection = _mapping(source.get("collection"))
        samples = collection.get("candidate_feature_samples")
        if not isinstance(samples, list):
            raise CandidateFreezeError("candidate_feature_samples_missing")
        selection = selector(
            samples,
            dataset_id=str(_mapping(source.get("dataset"))["dataset_id"]),
            dataset_sha256=str(_mapping(source.get("dataset"))["dataset_sha256"]),
            expected_binding=_mapping(source.get("binding")),
            directional_feature_fields=_candidate_features(diagnostics),
            diagnostic_hash=str(diagnostics["diagnostic_hash"]),
            repeatability_profile_id=provenance["repeatability_profile_id"],
            repeatability_evidence_sha256=provenance["repeatability_evidence_sha256"],
            revision_evidence_sha256=provenance["revision_evidence_sha256"],
            numeric_tolerance=provenance["numeric_tolerance"],
        )
        source_checks = _mapping(source.get("checks"))
        checks = {
            "source_live_collection_passed": source.get("status") == "PASS",
            "actual_test_database_verified": source_checks.get("test_database_identity")
            is True,
            "provider_collection_complete": source_checks.get("provider_calls_complete")
            is True,
            "candidate_feature_projection_complete": source_checks.get(
                "candidate_feature_projection_complete"
            )
            is True,
            "repeatability_profile_admitted": provenance[
                "repeatability_profile_admitted"
            ],
            "immutable_revision_admitted": provenance["immutable_revision_admitted"],
            "selection_used_calibration_only": selection.get("dataset", {}).get(
                "partition"
            )
            == "CALIBRATION",
            "holdout_remained_sealed": (
                selection.get("holdout", {}).get("status") == "SEALED_NOT_OPENED"
                and _mapping(source.get("dataset")).get("holdout_status")
                == "SEALED_NOT_COLLECTED"
            ),
            "candidate_policy_frozen": selection.get("status") == "FROZEN",
            "runtime_activation_prohibited": (
                selection.get("runtime_activation_permitted") is False
                and (
                    selection.get("frozen_policy") is None
                    or _mapping(selection.get("frozen_policy")).get(
                        "runtime_activation_permitted"
                    )
                    is False
                )
            ),
            "restart_readback_exact": source_checks.get("restart_readback_exact")
            is True,
            "cleanup_complete": source_checks.get("cleanup_complete") is True,
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "PASS" if not failed_checks else "FAIL",
            "failure_code": (
                None if not failed_checks else "candidate_policy_freeze_failed"
            ),
            "service_id": source.get("service_id"),
            "profile": source.get("profile"),
            "redacted_database_url": source.get("redacted_database_url"),
            "migration": source.get("migration"),
            "dataset": source.get("dataset"),
            "binding": source.get("binding"),
            "provider_observation": source.get("provider_observation"),
            "provider_request_counts": source.get("provider_request_counts"),
            "source_collection": {
                "sample_count": collection.get("sample_count"),
                "candidate_feature_sample_count": len(samples),
                "sample_set_hash": collection.get("sample_set_hash"),
                "diagnostic_hash": diagnostics.get("diagnostic_hash"),
            },
            "provenance": provenance,
            "selection": selection,
            "persistence": source.get("persistence"),
            "checks": checks,
            "failed_checks": failed_checks,
        }
    except CandidateFreezeError as exc:
        result = _failure(exc.failure_code, detail=exc.detail)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = _failure(
            "candidate_policy_freeze_failed",
            detail={
                "exception": exc.__class__.__name__,
                "message": str(exc)[:160],
            },
        )
    _assert_redacted(result, env)
    return result


class CandidateFreezeError(ValueError):
    def __init__(self, failure_code: str, detail: object | None = None) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.detail = detail


def _admit_provenance(
    source: Mapping[str, Any],
    *,
    repeatability: Mapping[str, Any],
    revision: Mapping[str, Any],
    repeatability_sha256: str,
    revision_sha256: str,
) -> dict[str, Any]:
    repeatability_checks = _mapping(repeatability.get("checks"))
    revision_checks = _mapping(revision.get("checks"))
    profile = _mapping(repeatability.get("candidate_profile"))
    repeatability_binding = _mapping(profile.get("binding"))
    measurement = _mapping(profile.get("measurement"))
    policy = _mapping(profile.get("policy"))
    revision_binding = _mapping(revision.get("binding"))
    source_binding = _mapping(source.get("binding"))
    repeatability_admitted = (
        repeatability.get("status") == "PASS"
        and profile.get("status") == "CANDIDATE"
        and REQUIRED_REPEATABILITY_CHECKS.issubset(repeatability_checks)
        and all(
            repeatability_checks.get(name) is True
            for name in REQUIRED_REPEATABILITY_CHECKS
        )
        and measurement.get("repeat_count") == 5
        and measurement.get("observation_count") == 600
    )
    revision_admitted = (
        revision.get("status") == "PASS"
        and REQUIRED_REVISION_CHECKS.issubset(revision_checks)
        and all(revision_checks.get(name) is True for name in REQUIRED_REVISION_CHECKS)
        and repeatability_binding.get("model_name")
        == revision_binding.get("served_model_name")
        and repeatability_binding.get("deployment_id")
        == revision_binding.get("deployment_id")
        and source_binding.get("reranker_model_revision")
        == revision_binding.get("artifact_revision")
        and source_binding.get("ranking_policy_id")
        == repeatability_binding.get("retrieval_policy_id")
    )
    tolerance = policy.get("score_delta_tolerance")
    if (
        not repeatability_admitted
        or not revision_admitted
        or isinstance(tolerance, bool)
        or not isinstance(tolerance, int | float)
        or not 0.0 < float(tolerance) <= 0.005
    ):
        raise CandidateFreezeError("source_provenance_not_admitted")
    return {
        "repeatability_profile_admitted": True,
        "immutable_revision_admitted": True,
        "repeatability_profile_id": str(profile["profile_id"]),
        "repeatability_evidence_sha256": repeatability_sha256,
        "revision_evidence_sha256": revision_sha256,
        "served_model_name": revision_binding["served_model_name"],
        "artifact_revision": revision_binding["artifact_revision"],
        "numeric_tolerance": float(tolerance),
        "repeat_count": measurement["repeat_count"],
        "observation_count": measurement["observation_count"],
        "cross_label_rank_exchange_count": _mapping(
            repeatability.get("repeatability")
        ).get("cross_label_rank_exchange_count"),
    }


def _candidate_features(diagnostics: Mapping[str, Any]) -> tuple[str, ...]:
    correction = _mapping(diagnostics.get("feature_set_correction"))
    declared = {
        *correction.get("current_feature_fields", []),
        *correction.get("corrected_candidate_fields", []),
    }
    features = tuple(field for field in SELECTABLE_FEATURE_FIELDS if field in declared)
    if features != SELECTABLE_FEATURE_FIELDS:
        raise CandidateFreezeError("candidate_features_unavailable")
    return features


def _read_json(path: Path) -> tuple[str, Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, Mapping):
        raise TypeError("evidence document is invalid")
    return text, value


def _failure(failure_code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": failure_code,
    }
    if detail is not None:
        result["detail"] = detail
    return result


def _assert_redacted(result: Mapping[str, Any], environ: Mapping[str, str]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for key in s20qe.PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value in serialized:
            raise ValueError("protected value leaked into evidence")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        frozen = _mapping(_mapping(result.get("selection")).get("frozen_policy"))
        return (
            "gb2_s20qg_candidate_policy_freeze=pass "
            f"features={len(frozen.get('feature_fields', []))} "
            "holdout=sealed activation=prohibited"
        )
    if status == "skipped":
        return "gb2_s20qg_candidate_policy_freeze=skipped"
    return (
        "gb2_s20qg_candidate_policy_freeze=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qg_candidate_policy_freeze()
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
