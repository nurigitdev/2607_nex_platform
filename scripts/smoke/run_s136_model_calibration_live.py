#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-mo"):
    sys.path.insert(0, str(path))

from nex_mo.remote_provider import (  # noqa: E402
    build_remote_reranker_execution_config,
    execute_remote_rerank_request,
)
from nex_runtime import (  # noqa: E402
    BinaryCalibrationConstraints,
    build_model_calibration_profile,
    evaluate_binary_score_calibration,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "s136_model_calibration_live.v1"
SMOKE_ENV = "NEX_S136_MODEL_CALIBRATION_LIVE"
DEFAULT_DATASET_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_reranker_calibration_v1.json"
)
POLICY_ID = "weighted_rrf_vector_bm25_v1"
SCORE_SEMANTICS = "provider_native_relevance_0_1"
HttpRequester = Callable[..., Any]


def run_s136_model_calibration_live(
    environ: Mapping[str, str] | None = None,
    *,
    dataset_path: Path = DEFAULT_DATASET_PATH,
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
        config = build_remote_reranker_execution_config(effective_env)
        if not config.configured:
            raise ValueError("Remote reranker provider endpoint is not configured.")
        dataset = _load_dataset(dataset_path)
        samples, observed_models = _collect_samples(
            dataset,
            environ=effective_env,
            requester=requester,
        )
        evaluation = evaluate_binary_score_calibration(
            samples,
            dataset_id=str(dataset["dataset_id"]),
            constraints=BinaryCalibrationConstraints(),
        )
        stable_model = len(observed_models) == 1 and config.model_revision in observed_models
        checks = {
            "minimum_samples_collected": len(samples) >= 20,
            "positive_samples_collected": sum(
                bool(sample["expected_ready"]) for sample in samples
            )
            >= 8,
            "negative_samples_collected": sum(
                not bool(sample["expected_ready"]) for sample in samples
            )
            >= 8,
            "model_revision_stable": stable_model,
            "evaluation_passed": evaluation["status"] == "PASSED",
        }
        profile = None
        if all(checks.values()):
            profile = build_model_calibration_profile(
                profile_id=(
                    "reranking-"
                    f"{_safe_identifier(config.model_revision)}-"
                    "weighted-rrf-v1"
                ),
                version="0001",
                status="CANDIDATE",
                capability="reranking",
                model_revision=config.model_revision,
                request_shape=config.request_shape,
                score_semantics=SCORE_SEMANTICS,
                policy_id=POLICY_ID,
                evaluation=evaluation,
            )
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "model_binding": {
                "capability": "reranking",
                "model_revision": config.model_revision,
                "request_shape": config.request_shape,
                "score_semantics": SCORE_SEMANTICS,
                "policy_id": POLICY_ID,
            },
            "evaluation": evaluation,
            "candidate_profile": profile,
            "sample_scores_persisted": False,
            "sample_text_persisted": False,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "calibration_execution_failed",
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, effective_env, dataset_path)
    return result


def _load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("dataset_schema_version")
        != "model_calibration_dataset.v1"
        or not isinstance(payload.get("dataset_id"), str)
        or not isinstance(payload.get("cases"), list)
        or not payload["cases"]
    ):
        raise ValueError("Calibration dataset is invalid.")
    return payload


def _collect_samples(
    dataset: Mapping[str, Any],
    *,
    environ: Mapping[str, str],
    requester: HttpRequester | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    samples: list[dict[str, Any]] = []
    models: set[str] = set()
    for case in dataset["cases"]:
        case_id = _required_string(case.get("case_id"), "case_id")
        query = _required_string(case.get("query"), "query")
        documents = case.get("documents")
        if not isinstance(documents, list) or not documents:
            raise ValueError("documents must be a non-empty list.")
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
        models.add(_required_string(response.get("model_revision"), "model_revision"))
        by_index = {
            int(item["index"]): float(item["score"])
            for item in response.get("results", [])
            if isinstance(item, Mapping)
        }
        if set(by_index) != set(range(len(documents))):
            raise ValueError("Reranker response did not score every document.")
        for index, document in enumerate(documents):
            expected_ready = document.get("expected_ready")
            if not isinstance(expected_ready, bool):
                raise ValueError("expected_ready must be boolean.")
            document_id = _required_string(document.get("document_id"), "document_id")
            samples.append(
                {
                    "sample_id": f"{case_id}:{document_id}",
                    "expected_ready": expected_ready,
                    "score": by_index[index],
                }
            )
    return samples, models


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    dataset_path: Path,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected_values = [
        str(environ.get("NEX_MO_REMOTE_RERANKER_URL", "")),
        str(environ.get("NEX_MO_REMOTE_RERANKER_API_KEY", "")),
    ]
    try:
        dataset = _load_dataset(dataset_path)
    except (OSError, ValueError, TypeError):
        dataset = None
    if dataset is not None:
        protected_values.extend(
            str(document["text"])
            for case in dataset["cases"]
            for document in case["documents"]
        )
    if any(len(value) >= 4 and value in serialized for value in protected_values):
        raise ValueError("Calibration evidence contains protected request data.")


def _safe_identifier(value: str) -> str:
    normalized = "".join(
        character.lower() if character.isalnum() else "-"
        for character in value
    )
    return "-".join(part for part in normalized.split("-") if part)


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"s136_model_calibration_live=skipped reason={SMOKE_ENV}"
    if status == "pass":
        evaluation = result.get("evaluation", {})
        binding = result.get("model_binding", {})
        return (
            "s136_model_calibration_live=pass "
            f"model={binding.get('model_revision')} "
            f"samples={evaluation.get('sample_count')} "
            f"threshold={evaluation.get('selected_threshold')}"
        )
    return (
        "s136_model_calibration_live=fail "
        f"checks={','.join(result.get('failed_checks') or []) or 'execution'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_s136_model_calibration_live(dataset_path=args.dataset)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
