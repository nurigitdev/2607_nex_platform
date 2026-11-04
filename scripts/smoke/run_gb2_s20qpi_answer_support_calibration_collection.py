#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from check_retrieval_calibration_v4_dataset import (
    DEFAULT_DATASET_PATH,
    check_retrieval_calibration_v4_dataset,
)
from nex_cx.retrieval_answer_support_collection import (
    collect_answer_support_calibration,
    validate_answer_support_calibration_collection,
)
from nex_mo import remote_provider
from nex_runtime.model_artifact_revision import (
    admit_model_artifact_revision_evidence,
    model_artifact_revision_evidence_digest,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpi_answer_support_calibration_collection.v1"
SMOKE_ENV = "NEX_GB2_S20QPI_ANSWER_SUPPORT_COLLECTION"
PROFILE_ENV = "NEX_GB2_S20QPI_PROFILE"
SOURCE_ENV = "NEX_GB2_S20QPI_SOURCE_EVIDENCE"
ARTIFACT_ENV = "NEX_GB2_S20QPI_GENERATION_ARTIFACT_EVIDENCE"
DEFAULT_SOURCE = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpca_vector_near_tie_boundary.json"
)
DESIGN_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_signal_v1_design.json"
)
REQUEST_PROFILE_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_generation_profile_v1.json"
)
OUTPUT_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpi_answer_support_calibration_collection.json"
)
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
EXPECTED_PACKAGES = 160
EXPECTED_CANDIDATES = 640
MAXIMUM_PROVIDER_CONCURRENCY = 4
PROTECTED_ENV_KEYS = (
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

Collector = Callable[..., dict[str, Any]]
HttpRequester = Callable[..., Any]


def run_gb2_s20qpi_answer_support_calibration_collection(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    collector: Collector = collect_answer_support_calibration,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")
    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", detail=issues)
    try:
        source, source_hash = _load_json_with_hash(
            Path(effective_env.get(SOURCE_ENV, str(DEFAULT_SOURCE)))
        )
        artifact, _ = _load_json_with_hash(Path(effective_env[ARTIFACT_ENV]))
        artifact_revision = admit_model_artifact_revision_evidence(artifact)
        artifact_hash = model_artifact_revision_evidence_digest(artifact)
        configured_revision = effective_env.get("NEX_MO_VLLM_MODEL_REVISION")
        if configured_revision not in {None, "", artifact_revision}:
            raise ValueError("configured generation revision differs from attestation")
        effective_env["NEX_MO_VLLM_MODEL_REVISION"] = artifact_revision
        admission = check_retrieval_calibration_v4_dataset()
        dataset = _load_json(DEFAULT_DATASET_PATH)
        design = _load_json(DESIGN_PATH)
        request_profile = _load_json(REQUEST_PROFILE_PATH)
        calibration, holdout_values = _calibration_cases(dataset)
        source_alignment = _source_alignment(source, calibration, admission)
        guarded, request_counts = _holdout_guarded_requester(
            requester,
            holdout_values=holdout_values,
            environ=effective_env,
        )
        evaluation_count = 0
        evaluation_count_lock = Lock()

        def evaluate(
            payload: Mapping[str, Any], request_id: str, trace_id: str
        ) -> Mapping[str, Any]:
            nonlocal evaluation_count
            with evaluation_count_lock:
                evaluation_count += 1
            return remote_provider.execute_remote_generation_request(
                dict(payload),
                request_id=request_id,
                trace_id=trace_id,
                environ=effective_env,
                requester=guarded,
            )

        collection = collector(
            calibration,
            dataset_id=str(admission["dataset_id"]),
            dataset_sha256=str(admission["dataset_sha256"]),
            design=design,
            profile=request_profile,
            artifact_revision=artifact_revision,
            artifact_evidence_hash=artifact_hash,
            source_retrieval_evidence_hash=source_hash,
            evaluator=evaluate,
            maximum_concurrency=MAXIMUM_PROVIDER_CONCURRENCY,
        )
        normalized = validate_answer_support_calibration_collection(collection)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        remote_provider.ProviderRouteError,
    ) as exc:
        result = _failure(
            "collection_failed",
            detail={"exception": exc.__class__.__name__},
        )
        _assert_redacted(result, effective_env)
        return result

    dataset_evidence = _mapping(normalized.get("dataset"))
    checks = {
        "v4_dataset_immutable_admission_passed": admission["status"] == "PASS",
        "source_retrieval_evidence_admitted": source_alignment["status"] == "PASS",
        "source_actual_test_database_identity": source.get("database_identity")
        == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
        "generation_artifact_revision_attested": (
            normalized["provider_binding"]["model_revision"] == artifact_revision
        ),
        "calibration_package_count_complete": (
            dataset_evidence.get("package_count") == EXPECTED_PACKAGES
            and evaluation_count == EXPECTED_PACKAGES
        ),
        "calibration_candidate_count_complete": (
            dataset_evidence.get("candidate_count") == EXPECTED_CANDIDATES
        ),
        "provider_http_requests_accounted": (
            request_counts["generation"] >= EXPECTED_PACKAGES
            and request_counts["total"] == request_counts["generation"]
        ),
        "holdout_never_reached_provider": request_counts["holdout_blocked"] == 0,
        "holdout_remained_sealed": (
            dataset_evidence.get("holdout_status") == "SEALED_NOT_ACCESSED"
            and normalized["safety"]["holdout_access_permitted"] is False
        ),
        "candidate_truth_not_persisted": (
            normalized["privacy"]["candidate_truth_persisted"] is False
        ),
        "runtime_activation_prohibited": (
            normalized["safety"]["runtime_activation_permitted"] is False
        ),
    }
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-I",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "CALIBRATION_EVIDENCE_COLLECTED_P_J_REQUIRED",
        "database_calls": 0,
        "source_database_identity": source.get("database_identity"),
        "provider_evaluation_count": evaluation_count,
        "provider_maximum_concurrency": MAXIMUM_PROVIDER_CONCURRENCY,
        "provider_http_request_counts": request_counts,
        "artifact_revision": artifact_revision,
        "artifact_evidence_hash": artifact_hash,
        "source_alignment": source_alignment,
        "collection": normalized,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    _assert_redacted(result, effective_env, dataset=dataset)
    return result


def _configuration_issues(environ: Mapping[str, str]) -> list[str]:
    issues = []
    if not (
        environ.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
        or environ.get("NEX_MO_VLLM_BASE_URL")
    ):
        issues.append("generation_endpoint")
    for key in (
        "NEX_MO_VLLM_API_KEY",
        "NEX_MO_VLLM_MODEL",
        "NEX_MO_VLLM_DEPLOYMENT_ID",
        ARTIFACT_ENV,
    ):
        if not environ.get(key):
            issues.append(key)
    return issues


def _calibration_cases(
    dataset: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], tuple[str, ...]]:
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Dataset v4 cases are invalid")
    calibration = [case for case in cases if case.get("partition") == "CALIBRATION"]
    holdout = [case for case in cases if case.get("partition") == "HOLDOUT"]
    holdout_values = tuple(
        [str(case["query"]) for case in holdout]
        + [str(candidate["text"]) for case in holdout for candidate in case["candidates"]]
    )
    if len(calibration) != EXPECTED_PACKAGES or len(holdout) != 40:
        raise ValueError("Dataset v4 partitions are invalid")
    return sorted(calibration, key=lambda row: str(row["case_id"])), holdout_values


def _source_alignment(
    source: Mapping[str, Any],
    calibration: Sequence[Mapping[str, Any]],
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    runs = _mapping(source.get("repeat_collection")).get("runs")
    first = runs[0] if isinstance(runs, list) and runs else None
    observations = _mapping(first).get("candidate_observations")
    if source.get("status") != "PASS" or not isinstance(observations, list):
        raise ValueError("source retrieval evidence is not admitted")
    source_dataset = _mapping(source.get("dataset"))
    if (
        source_dataset.get("dataset_id") != admission.get("dataset_id")
        or source_dataset.get("dataset_sha256") != admission.get("dataset_sha256")
        or source_dataset.get("holdout_status") != "SEALED_NOT_COLLECTED"
    ):
        raise ValueError("source retrieval dataset binding drifted")
    expected = {
        (
            f"{case['scenario_id']}:{'positive' if case['expected_ready'] else 'negative'}",
            str(candidate["candidate_id"]),
        )
        for case in calibration
        for candidate in case["candidates"]
    }
    actual = {
        (str(row.get("sample_id")), str(row.get("candidate_id")))
        for row in observations
        if isinstance(row, Mapping)
    }
    if actual != expected or len(actual) != EXPECTED_CANDIDATES:
        raise ValueError("source retrieval candidate scope drifted")
    return {
        "status": "PASS",
        "source_slice_id": source.get("slice_id"),
        "candidate_scope_hash": semantic_sha256_hash_ref(sorted(expected)),
        "candidate_count": len(actual),
        "holdout_status": "SEALED_NOT_COLLECTED",
    }


def _holdout_guarded_requester(
    requester: HttpRequester | None,
    *,
    holdout_values: Sequence[str],
    environ: Mapping[str, str],
) -> tuple[HttpRequester, dict[str, int]]:
    base = requester or remote_provider.httpx.request
    config = remote_provider.build_remote_generation_execution_config(dict(environ))
    counts = {"total": 0, "generation": 0, "holdout_blocked": 0}
    counts_lock = Lock()

    def guarded(method: str, url: str, **kwargs: Any) -> Any:
        serialized = json.dumps(kwargs.get("json"), ensure_ascii=False, sort_keys=True)
        if any(value in serialized for value in holdout_values):
            with counts_lock:
                counts["holdout_blocked"] += 1
            raise ValueError("HOLDOUT content reached the generation provider")
        with counts_lock:
            counts["total"] += 1
            if url == config.url:
                counts["generation"] += 1
        return base(method, url, **kwargs)

    return guarded, counts


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError("evidence must be a JSON object")
    return value


def _load_json_with_hash(path: Path) -> tuple[Mapping[str, Any], str]:
    value = _load_json(path)
    return value, semantic_sha256_hash_ref(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    *,
    dataset: Mapping[str, Any] | None = None,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get(key, ""))
        for key in PROTECTED_ENV_KEYS
        if environ.get(key)
    ]
    if dataset is not None:
        cases = dataset.get("cases")
        if isinstance(cases, list):
            protected.extend(str(case["query"]) for case in cases)
            protected.extend(
                str(candidate["text"])
                for case in cases
                for candidate in case["candidates"]
            )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S20Q-P-I evidence contains protected data")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        collection = _mapping(result.get("collection"))
        dataset = _mapping(collection.get("dataset"))
        return (
            "gb2_s20qpi_answer_support_calibration_collection=pass "
            f"packages={dataset.get('package_count')} "
            f"candidates={dataset.get('candidate_count')} "
            f"provider_calls={result.get('provider_evaluation_count')} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpi_answer_support_calibration_collection=skipped"
    return (
        "gb2_s20qpi_answer_support_calibration_collection=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpi_answer_support_calibration_collection()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
