#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from check_model_calibration_dataset import (
    DEFAULT_V1_PATH,
    DEFAULT_V2_PATH,
    admit_calibration_dataset_files,
)
from nex_mo.provider_registry import ProviderRouteError
from nex_mo.remote_provider import (
    _remote_rerank_request_payload,
    build_remote_reranker_execution_config,
    execute_remote_rerank_request,
)
from nex_runtime import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
    is_immutable_model_revision,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_protected_dgx_live_profile import (
    protected_dgx_vllm_profile_defaults,
)

SCHEMA_VERSION = "gb2_s20o_provider_profile_audit.v1"
SMOKE_ENV = "NEX_GB2_S20O_RERANKER_LIVE"
V1_PROFILE_ID = "CURRENT_DEFAULT_TEMPLATE_V1"
V2_PROFILE_ID = "EXPLICIT_ENTERPRISE_RETRIEVAL_V1"
V2_CALIBRATION_PARTITION = "CALIBRATION"
BUSINESS_RETRIEVAL_INSTRUCTION = (
    "Given an enterprise work query, retrieve passages that directly and "
    "sufficiently answer the query while distinguishing closely related "
    "business operations."
)
RUNTIME_ENV = {
    "vllm_version": "NEX_GB2_S20O_VLLM_VERSION",
    "model_source_revision": "NEX_GB2_S20O_MODEL_SOURCE_REVISION",
    "sequence_classifier_override": ("NEX_GB2_S20O_SEQUENCE_CLASSIFIER_OVERRIDE"),
    "qwen3_reranker_template": "NEX_GB2_S20O_QWEN3_RERANKER_TEMPLATE",
}
EXPECTED_SCORE_SEMANTICS = "qwen3_yes_class_probability_0_1"
CURRENT_SCORE_SEMANTICS = "provider_native_relevance_0_1"
HttpRequester = Callable[..., Any]


def run_gb2_s20o_provider_profile_audit(
    environ: Mapping[str, str] | None = None,
    *,
    v1_path: Path = DEFAULT_V1_PATH,
    v2_path: Path = DEFAULT_V2_PATH,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    effective_env = {**protected_dgx_vllm_profile_defaults(), **env}
    try:
        admitted = admit_calibration_dataset_files(
            v1_path=v1_path,
            v2_path=v2_path,
        )
        datasets = {
            "v1": json.loads(v1_path.read_text(encoding="utf-8")),
            "v2_calibration": _v2_calibration_dataset(
                json.loads(v2_path.read_text(encoding="utf-8"))
            ),
        }
        config = build_remote_reranker_execution_config(effective_env)
        if not config.configured:
            raise ValueError("Remote reranker provider endpoint is not configured.")

        source_audit = _source_and_runtime_audit(config, effective_env)
        profiles = _request_profiles()
        observations: list[dict[str, Any]] = []
        for profile in profiles:
            profile_requester = _profile_requester(
                requester,
                instruction=profile.get("instruction"),
            )
            for dataset_key, dataset in datasets.items():
                observations.extend(
                    _collect_profile_observations(
                        dataset,
                        dataset_key=dataset_key,
                        profile_id=str(profile["profile_id"]),
                        environ=effective_env,
                        requester=profile_requester,
                    )
                )

        evaluation = _evaluate_profiles(observations)
        decision = _profile_decision(
            source_audit=source_audit,
            evaluation=evaluation,
        )
        observed_models = {item["model_revision"] for item in observations}
        observed_deployments = {item["deployment_id"] for item in observations}
        checks = {
            "datasets_admitted": admitted["v2"]["pair_count"] == 120,
            "v2_holdout_remained_sealed": all(
                item["dataset_key"] != "v2_holdout" for item in observations
            ),
            "profile_replay_complete": len(observations) == 232,
            "model_identity_stable": observed_models == {config.model_revision},
            "deployment_identity_stable": observed_deployments
            == {config.deployment_id},
            "scores_finite_and_bounded": _scores_finite_and_bounded(observations),
            "profile_evaluations_complete": set(evaluation)
            == {V1_PROFILE_ID, V2_PROFILE_ID},
            "audit_decision_recorded": decision["code"]
            in {
                "PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED",
                "REQUEST_PROFILE_ISSUE_CONFIRMED",
                "REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS",
                "GENUINE_SINGLE_SCORE_LIMITATION_CONFIRMED",
            },
        }
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "evidence_generated_at": _utc_now(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "decision": decision,
            "source_and_runtime_audit": source_audit,
            "request_profiles": [
                {key: value for key, value in profile.items() if key != "instruction"}
                for profile in profiles
            ],
            "dataset_binding": {
                "v1_dataset_id": admitted["v1"]["dataset_id"],
                "v1_file_sha256": admitted["v1"]["file_sha256"],
                "v1_pair_count": 36,
                "v2_dataset_id": admitted["v2"]["dataset_id"],
                "v2_dataset_sha256": admitted["v2"]["dataset_sha256"],
                "v2_calibration_pair_count": 80,
                "v2_holdout_status": "SEALED_NOT_OPENED",
            },
            "profile_evaluation": evaluation,
            "score_observations": observations,
            "raw_text_persisted": False,
            "provider_endpoint_persisted": False,
            "provider_credential_persisted": False,
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        httpx.HTTPError,
        ProviderRouteError,
    ) as exc:
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "provider_profile_audit_failed",
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, effective_env, (v1_path, v2_path))
    return result


def _source_and_runtime_audit(
    config: Any, environ: Mapping[str, str]
) -> dict[str, Any]:
    current_request = _remote_rerank_request_payload(
        config,
        "audit-query",
        ["audit-document"],
        1,
    )
    source_revision = environ.get(RUNTIME_ENV["model_source_revision"], "").strip()
    runtime = {
        "vllm_version": _runtime_value(environ.get(RUNTIME_ENV["vllm_version"])),
        "model_source_revision": _runtime_value(source_revision),
        "sequence_classifier_override": _runtime_confirmation(
            environ.get(RUNTIME_ENV["sequence_classifier_override"])
        ),
        "qwen3_reranker_template": _runtime_confirmation(
            environ.get(RUNTIME_ENV["qwen3_reranker_template"])
        ),
    }
    findings = {
        "current_product_request_uses_explicit_instruction": (
            "instruction" in current_request
        ),
        "current_score_semantics_is_model_specific": (
            CURRENT_SCORE_SEMANTICS == EXPECTED_SCORE_SEMANTICS
        ),
        "normalization_is_structural_not_probability_transform": True,
        "normalization_rounds_score_to_six_decimals": True,
        "immutable_model_source_revision_bound": is_immutable_model_revision(
            source_revision
        )
        and source_revision == config.model_revision,
        "sequence_classifier_override_confirmed": (
            runtime["sequence_classifier_override"] == "CONFIRMED"
        ),
        "qwen3_reranker_template_confirmed": (
            runtime["qwen3_reranker_template"] == "CONFIRMED"
        ),
    }
    runtime_profile_confirmed = all(
        findings[name]
        for name in (
            "immutable_model_source_revision_bound",
            "sequence_classifier_override_confirmed",
            "qwen3_reranker_template_confirmed",
        )
    )
    return {
        "official_model_behavior": {
            "instruction_aware": True,
            "recommended_multilingual_instruction_language": "ENGLISH",
            "score_semantics": EXPECTED_SCORE_SEMANTICS,
            "higher_score_means_more_relevant": True,
        },
        "current_product_behavior": {
            "request_shape": config.request_shape,
            "explicit_instruction": False,
            "score_semantics_label": CURRENT_SCORE_SEMANTICS,
            "score_normalization": "STRUCTURAL_PASSTHROUGH_ROUNDED_6DP",
            "model_revision": config.model_revision,
            "deployment_id": config.deployment_id,
        },
        "runtime_provenance": runtime,
        "findings": findings,
        "runtime_profile_confirmed": runtime_profile_confirmed,
    }


def _request_profiles() -> list[dict[str, Any]]:
    instruction_hash = semantic_sha256_hash_ref(BUSINESS_RETRIEVAL_INSTRUCTION)
    return [
        {
            "profile_id": V1_PROFILE_ID,
            "instruction_mode": "SERVER_DEFAULT_TEMPLATE",
            "instruction_hash": None,
            "instruction": None,
        },
        {
            "profile_id": V2_PROFILE_ID,
            "instruction_mode": "EXPLICIT_REQUEST_INSTRUCTION",
            "instruction_hash": instruction_hash,
            "instruction": BUSINESS_RETRIEVAL_INSTRUCTION,
        },
    ]


def _profile_requester(
    requester: HttpRequester | None,
    *,
    instruction: object,
) -> HttpRequester | None:
    if instruction is None:
        return requester
    if not isinstance(instruction, str) or not instruction:
        raise ValueError("Audit instruction must be a non-empty string.")
    base = requester or httpx.request

    def wrapped(method: str, url: str, **kwargs: Any) -> Any:
        payload = kwargs.get("json")
        if not isinstance(payload, dict):
            raise TypeError("Reranker audit request JSON is unavailable.")
        kwargs["json"] = {**payload, "instruction": instruction}
        return base(method, url, **kwargs)

    return wrapped


def _collect_profile_observations(
    dataset: Mapping[str, Any],
    *,
    dataset_key: str,
    profile_id: str,
    environ: Mapping[str, str],
    requester: HttpRequester | None,
) -> list[dict[str, Any]]:
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Calibration dataset cases must be a non-empty list.")
    observations: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise TypeError("Calibration case must be an object.")
        case_id = _required_string(case.get("case_id"), "case_id")
        query = _required_string(case.get("query"), "query")
        documents = case.get("documents")
        if not isinstance(documents, list) or not documents:
            raise ValueError("Calibration documents must be a non-empty list.")
        if not all(isinstance(document, Mapping) for document in documents):
            raise TypeError("Calibration document must be an object.")
        response = execute_remote_rerank_request(
            {
                "alias": "reranker-default",
                "query": query,
                "documents": [
                    _required_string(document.get("text"), "text")
                    for document in documents
                ],
                "top_n": len(documents),
            },
            environ=dict(environ),
            requester=requester,
        )
        scores = _scores_by_index(response, len(documents))
        for index, document in enumerate(documents):
            expected_ready = document.get("expected_ready")
            if type(expected_ready) is not bool:
                raise ValueError("expected_ready must be boolean.")
            document_id = _required_string(document.get("document_id"), "document_id")
            observations.append(
                {
                    "profile_id": profile_id,
                    "dataset_key": dataset_key,
                    "pair_id": f"{case_id}:{document_id}",
                    "partition": str(case.get("partition", "FROZEN_V1")),
                    "relevance_grade": str(
                        document.get(
                            "relevance_grade",
                            "POSITIVE" if expected_ready else "NEGATIVE",
                        )
                    ),
                    "expected_ready": expected_ready,
                    "score": scores[index],
                    "model_revision": _required_string(
                        response.get("model_revision"), "model_revision"
                    ),
                    "deployment_id": _required_string(
                        response.get("deployment_id"), "deployment_id"
                    ),
                }
            )
    return observations


def _scores_by_index(
    response: Mapping[str, Any], expected_count: int
) -> dict[int, float]:
    results = response.get("results")
    if not isinstance(results, list) or len(results) != expected_count:
        raise ValueError("Reranker response coverage is incomplete.")
    scores: dict[int, float] = {}
    for item in results:
        if not isinstance(item, Mapping):
            raise TypeError("Reranker result must be an object.")
        index = item.get("index")
        score = item.get("score")
        if (
            type(index) is not int
            or isinstance(score, bool)
            or not isinstance(score, int | float)
            or index in scores
        ):
            raise ValueError("Reranker result index or score is invalid.")
        scores[index] = float(score)
    if set(scores) != set(range(expected_count)):
        raise ValueError("Reranker response indexes are incomplete.")
    return scores


def _evaluate_profiles(
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for profile_id in (V1_PROFILE_ID, V2_PROFILE_ID):
        datasets: dict[str, Any] = {}
        for dataset_key in ("v1", "v2_calibration"):
            samples = [
                {
                    "sample_id": item["pair_id"],
                    "expected_ready": item["expected_ready"],
                    "score": item["score"],
                }
                for item in observations
                if item["profile_id"] == profile_id
                and item["dataset_key"] == dataset_key
            ]
            datasets[dataset_key] = evaluate_binary_score_calibration(
                samples,
                dataset_id=f"s20o:{dataset_key}:{profile_id}",
                constraints=BinaryCalibrationConstraints(),
            )
        result[profile_id] = datasets
    return result


def _profile_decision(
    *,
    source_audit: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    current = evaluation[V1_PROFILE_ID]["v2_calibration"]
    explicit = evaluation[V2_PROFILE_ID]["v2_calibration"]
    current_overlap = float(current["score_distribution"]["overlap"])
    explicit_overlap = float(explicit["score_distribution"]["overlap"])
    if explicit["status"] == "PASSED" and current["status"] != "PASSED":
        score_code = "REQUEST_PROFILE_ISSUE_CONFIRMED"
        score_reason = "explicit_instruction_admitted_single_signal"
    elif explicit_overlap < current_overlap:
        score_code = "REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS"
        score_reason = "explicit_instruction_reduced_overlap_without_admission"
    else:
        score_code = "GENUINE_SINGLE_SCORE_LIMITATION_CONFIRMED"
        score_reason = "explicit_instruction_did_not_reduce_overlap"
    if not source_audit["runtime_profile_confirmed"]:
        code = "PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED"
        reason = "runtime_template_override_or_revision_binding_unconfirmed"
    else:
        code = score_code
        reason = score_reason
    return {
        "code": code,
        "reason": reason,
        "score_profile_assessment": {
            "code": score_code,
            "reason": score_reason,
        },
        "current_v2_status": current["status"],
        "explicit_v2_status": explicit["status"],
        "current_v2_overlap": current_overlap,
        "explicit_v2_overlap": explicit_overlap,
        "labels_changed": False,
        "constraints_changed": False,
        "runtime_activation_allowed": False,
        "next_slice": "GB2-CA00-S20P",
    }


def _v2_calibration_dataset(dataset: Mapping[str, Any]) -> dict[str, Any]:
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("v2 calibration cases are invalid.")
    calibration = [
        case
        for case in cases
        if isinstance(case, Mapping)
        and case.get("partition") == V2_CALIBRATION_PARTITION
    ]
    if len(calibration) != 20:
        raise ValueError("v2 calibration partition coverage is incomplete.")
    return {"cases": calibration}


def _scores_finite_and_bounded(observations: list[dict[str, Any]]) -> bool:
    import math

    return all(
        math.isfinite(float(item["score"])) and 0.0 <= float(item["score"]) <= 1.0
        for item in observations
    )


def _runtime_confirmation(value: str | None) -> str:
    if value is None or not value.strip():
        return "UNCONFIRMED"
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return "CONFIRMED"
    if normalized in {"0", "false", "no", "off"}:
        return "NOT_CONFIGURED"
    raise ValueError("Runtime confirmation must be boolean.")


def _runtime_value(value: str | None) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "UNCONFIRMED"


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    dataset_paths: tuple[Path, ...],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get("NEX_MO_REMOTE_RERANKER_URL", "")),
        str(environ.get("NEX_MO_REMOTE_RERANKER_API_KEY", "")),
    ]
    for path in dataset_paths:
        try:
            dataset = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(dataset, Mapping):
            continue
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
        raise ValueError("Provider profile evidence contains protected data.")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20o_provider_profile_audit=skipped reason={SMOKE_ENV}"
    if status == "pass":
        decision = result.get("decision", {})
        return (
            "gb2_s20o_provider_profile_audit=pass "
            f"decision={decision.get('code')} "
            f"current_overlap={decision.get('current_v2_overlap')} "
            f"explicit_overlap={decision.get('explicit_v2_overlap')}"
        )
    return (
        "gb2_s20o_provider_profile_audit=fail "
        f"checks={','.join(result.get('failed_checks') or []) or 'execution'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--v1-dataset", type=Path, default=DEFAULT_V1_PATH)
    parser.add_argument("--v2-dataset", type=Path, default=DEFAULT_V2_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_gb2_s20o_provider_profile_audit(
        v1_path=args.v1_dataset,
        v2_path=args.v2_dataset,
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
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
