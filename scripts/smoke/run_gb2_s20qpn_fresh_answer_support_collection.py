#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_collection import (
    collect_answer_support_calibration,
    validate_answer_support_calibration_collection,
)
from nex_cx.retrieval_answer_support_fresh_calibration import (
    admit_fresh_calibration_dataset,
    build_fresh_calibration_dataset,
)
from nex_mo import remote_provider
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpn_fresh_answer_support_collection.v1"
SMOKE_ENV = "NEX_GB2_S20QPN_FRESH_COLLECTION"
PROFILE_ENV = "NEX_GB2_S20QPN_PROFILE"
P_M_SOURCE_ENV = "NEX_GB2_S20QPN_P_M_EVIDENCE"
P_I_SOURCE_ENV = "NEX_GB2_S20QPN_P_I_EVIDENCE"
P_M_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpm_fresh_calibration_admission.json"
)
P_I_SOURCE_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpi_answer_support_calibration_collection.json"
)
FRESH_DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_fresh_calibration_v1_design.json"
)
SIGNAL_DESIGN_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_signal_v1_design.json"
)
REQUEST_PROFILE_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_generation_profile_v1.json"
)
PREDECESSOR_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4.json"
)
P_L_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpl_canonical_profile_freeze.json"
)
OUTPUT_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpn_fresh_answer_support_collection.json"
)
EXPECTED_PACKAGES = 200
EXPECTED_CANDIDATES = 800
MAXIMUM_PROVIDER_CONCURRENCY = 4
PROTECTED_ENV_KEYS = (
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)

Collector = Callable[..., dict[str, Any]]
Validator = Callable[[Mapping[str, Any]], dict[str, Any]]
Executor = Callable[..., Mapping[str, Any]]
HttpRequester = Callable[..., Any]


def run_gb2_s20qpn_fresh_answer_support_collection(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    collector: Collector = collect_answer_support_calibration,
    validator: Validator = validate_answer_support_calibration_collection,
    executor: Executor = remote_provider.execute_remote_generation_request,
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
    effective_env = {**protected_dgx_vllm_profile_defaults(), **env}
    effective_env["NEX_MO_PROVIDER_MODE"] = "live"
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", detail=issues)

    try:
        p_m_source = _load(
            Path(effective_env.get(P_M_SOURCE_ENV, str(P_M_SOURCE_PATH)))
        )
        p_i_source = _load(
            Path(effective_env.get(P_I_SOURCE_ENV, str(P_I_SOURCE_PATH)))
        )
        p_l_source = _load(P_L_SOURCE_PATH)
        fresh_design = _load(FRESH_DESIGN_PATH)
        signal_design = _load(SIGNAL_DESIGN_PATH)
        request_profile = _load(REQUEST_PROFILE_PATH)
        predecessor = _load(PREDECESSOR_PATH)
        freeze = _mapping(p_l_source.get("freeze"), "P-L freeze")
        dataset = build_fresh_calibration_dataset(
            fresh_design, p_l_freeze=freeze
        )
        admission = admit_fresh_calibration_dataset(
            dataset,
            design=fresh_design,
            p_l_freeze=freeze,
            predecessor_cases=predecessor["cases"],
        )
        p_m_admission = _mapping(p_m_source.get("admission"), "P-M admission")
        if (
            p_m_source.get("status") != "PASS"
            or p_m_admission.get("dataset_hash") != admission["dataset_hash"]
            or p_m_admission.get("design_hash") != admission["design_hash"]
        ):
            raise ValueError("P-M admission binding drifted")
        p_i_collection = _mapping(p_i_source.get("collection"), "P-I collection")
        provider_binding = _mapping(
            p_i_collection.get("provider_binding"), "P-I provider binding"
        )
        artifact_revision = _required_text(
            p_i_source.get("artifact_revision"), "artifact_revision"
        )
        artifact_hash = _required_text(
            p_i_source.get("artifact_evidence_hash"), "artifact_evidence_hash"
        )
        if (
            p_i_source.get("status") != "PASS"
            or provider_binding.get("model_revision") != artifact_revision
        ):
            raise ValueError("P-I provider binding is invalid")
        _bind_effective_provider(effective_env, provider_binding, artifact_revision)
        guarded, request_counts = _counting_requester(
            requester, environ=effective_env
        )
        evaluation_count = 0
        evaluation_lock = Lock()

        def evaluate(
            payload: Mapping[str, Any], request_id: str, trace_id: str
        ) -> Mapping[str, Any]:
            nonlocal evaluation_count
            with evaluation_lock:
                evaluation_count += 1
            return executor(
                dict(payload),
                request_id=request_id,
                trace_id=trace_id,
                environ=effective_env,
                requester=guarded,
            )

        collection = collector(
            dataset["cases"],
            dataset_id=admission["dataset_id"],
            dataset_sha256=admission["dataset_hash"],
            design=signal_design,
            profile=request_profile,
            artifact_revision=artifact_revision,
            artifact_evidence_hash=artifact_hash,
            source_retrieval_evidence_hash=admission["dataset_hash"],
            evaluator=evaluate,
            maximum_concurrency=MAXIMUM_PROVIDER_CONCURRENCY,
            request_namespace="s20qpn",
        )
        normalized = validator(collection)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        remote_provider.ProviderRouteError,
    ) as exc:
        result = _failure(
            "fresh_collection_failed", detail={"exception": exc.__class__.__name__}
        )
        _assert_redacted(result, effective_env)
        return result

    collection_dataset = _mapping(normalized.get("dataset"), "collection dataset")
    checks = {
        "p_m_dataset_bound": collection_dataset.get("dataset_sha256")
        == admission["dataset_hash"],
        "package_count_complete": collection_dataset.get("package_count")
        == EXPECTED_PACKAGES
        and evaluation_count == EXPECTED_PACKAGES,
        "candidate_count_complete": collection_dataset.get("candidate_count")
        == EXPECTED_CANDIDATES,
        "provider_binding_preserved": normalized.get("provider_binding")
        == dict(provider_binding),
        "provider_requests_accounted": request_counts["generation"]
        >= EXPECTED_PACKAGES
        and request_counts["total"] == request_counts["generation"],
        "holdout_absent": collection_dataset.get("holdout_status")
        == "SEALED_NOT_ACCESSED",
        "candidate_truth_not_persisted": normalized.get("privacy", {}).get(
            "candidate_truth_persisted"
        )
        is False,
        "runtime_activation_prohibited": normalized.get("safety", {}).get(
            "runtime_activation_permitted"
        )
        is False,
    }
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-N",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "FRESH_PROVIDER_EVIDENCE_COLLECTED_P_O_REQUIRED",
        "database_calls": 0,
        "provider_evaluation_count": evaluation_count,
        "provider_maximum_concurrency": MAXIMUM_PROVIDER_CONCURRENCY,
        "provider_http_request_counts": request_counts,
        "artifact_revision": artifact_revision,
        "artifact_evidence_hash": artifact_hash,
        "fresh_dataset_hash": admission["dataset_hash"],
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
    for key in ("NEX_MO_VLLM_API_KEY", "NEX_MO_VLLM_MODEL"):
        if not environ.get(key):
            issues.append(key)
    return issues


def _bind_effective_provider(
    environ: dict[str, str], binding: Mapping[str, Any], artifact_revision: str
) -> None:
    configured_revision = environ.get("NEX_MO_VLLM_MODEL_REVISION")
    if configured_revision not in {None, "", artifact_revision, "Qwen3.5-4B"}:
        raise ValueError("configured generation revision differs from P-I")
    configured_deployment = environ.get("NEX_MO_VLLM_DEPLOYMENT_ID")
    expected_deployment = _required_text(binding.get("deployment_id"), "deployment_id")
    if configured_deployment not in {
        None,
        "",
        expected_deployment,
        "vllm-generation-http",
    }:
        raise ValueError("configured generation deployment differs from P-I")
    environ["NEX_MO_VLLM_MODEL_REVISION"] = artifact_revision
    environ["NEX_MO_VLLM_DEPLOYMENT_ID"] = expected_deployment


def _counting_requester(
    requester: HttpRequester | None, *, environ: Mapping[str, str]
) -> tuple[HttpRequester, dict[str, int]]:
    base = requester or remote_provider.httpx.request
    config = remote_provider.build_remote_generation_execution_config(dict(environ))
    counts = {"total": 0, "generation": 0}
    lock = Lock()

    def guarded(method: str, url: str, **kwargs: Any) -> Any:
        with lock:
            counts["total"] += 1
            if url == config.url:
                counts["generation"] += 1
        return base(method, url, **kwargs)

    return guarded, counts


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    *,
    dataset: Mapping[str, Any] | None = None,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get(key, "")) for key in PROTECTED_ENV_KEYS if environ.get(key)
    ]
    if dataset is not None:
        protected.extend(str(row["query"]) for row in dataset["cases"])
        protected.extend(
            str(candidate["text"])
            for row in dataset["cases"]
            for candidate in row["candidates"]
        )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("P-N evidence contains protected data")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("evidence must be a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        collection = result.get("collection")
        collection = collection if isinstance(collection, Mapping) else {}
        dataset = collection.get("dataset")
        dataset = dataset if isinstance(dataset, Mapping) else {}
        return (
            "gb2_s20qpn_fresh_answer_support_collection=pass "
            f"packages={dataset.get('package_count')} "
            f"candidates={dataset.get('candidate_count')} "
            f"provider_calls={result.get('provider_evaluation_count')} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpn_fresh_answer_support_collection=skipped"
    return (
        "gb2_s20qpn_fresh_answer_support_collection=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpn_fresh_answer_support_collection()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
