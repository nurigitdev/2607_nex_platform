#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_embedding_revision_ab import (
    EmbeddingRevisionABError,
    build_embedding_revision_profile,
    compare_embedding_revision_profiles,
)
from nex_mo.provider_registry import ProviderRouteError
from nex_mo.remote_provider import (
    build_remote_embedding_execution_config,
    execute_remote_embedding_request,
)
from nex_runtime.semantic_hashes import sha256_text
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qk_embedding_revision_ab.v1"
SMOKE_ENV = "NEX_GB2_S20QK_EMBEDDING_REVISION_AB"
MODE_ENV = "NEX_GB2_S20QK_MODE"
SLOT_ENV = "NEX_GB2_S20QK_PROFILE_SLOT"
SOURCE_PATH_ENV = "NEX_GB2_S20QK_SOURCE_EVIDENCE_PATH"
ARTIFACT_PATH_ENV = "NEX_GB2_S20QK_ARTIFACT_EVIDENCE_PATH"
PROFILE_A_PATH_ENV = "NEX_GB2_S20QK_PROFILE_A_PATH"
PROFILE_B_PATH_ENV = "NEX_GB2_S20QK_PROFILE_B_PATH"
MODES = frozenset({"PROFILE", "COMPARE"})
PROTECTED_ENV_KEYS = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_CX_TEST_DATABASE_URL",
)

HttpRequester = Callable[..., Any]


def run_gb2_s20qk_embedding_revision_ab(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    mode = str(env.get(MODE_ENV, "")).strip().upper()
    effective_env = {**protected_dgx_vllm_profile_defaults(), **env}
    try:
        if mode not in MODES:
            raise EmbeddingRevisionABError("S20QK_MODE_INVALID")
        if mode == "PROFILE":
            result = _build_profile(effective_env, requester=requester)
        else:
            result = _compare_profiles(effective_env)
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "mode": mode,
            "result": result,
        }
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        httpx.HTTPError,
        ProviderRouteError,
        EmbeddingRevisionABError,
    ) as exc:
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "mode": mode or None,
            "failure_code": getattr(exc, "error_code", "S20QK_EXECUTION_FAILED"),
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(evidence, effective_env)
    return evidence


def _build_profile(
    env: Mapping[str, str], *, requester: HttpRequester | None
) -> dict[str, Any]:
    source_text, source = _read_json(_required_path(env, SOURCE_PATH_ENV))
    artifact_text, artifact = _read_json(_required_path(env, ARTIFACT_PATH_ENV))
    provider_binding = _probe_embedding(env, requester=requester)
    return build_embedding_revision_profile(
        source,
        artifact_evidence=artifact,
        provider_binding=provider_binding,
        slot=str(env.get(SLOT_ENV, "")),
        source_evidence_sha256=_text_hash(source_text),
        artifact_evidence_sha256=_text_hash(artifact_text),
    )


def _probe_embedding(
    env: Mapping[str, str], *, requester: HttpRequester | None
) -> dict[str, Any]:
    runtime_env = dict(env)
    config = build_remote_embedding_execution_config(runtime_env)
    if not config.configured:
        raise EmbeddingRevisionABError("S20QK_EMBEDDING_PROVIDER_NOT_CONFIGURED")
    response = execute_remote_embedding_request(
        {
            "alias": "s20qk-embedding-revision-probe",
            "inputs": [
                "프로젝트 비용 전표의 승인 근거를 조회한다.",
                "사내 식당의 오늘 메뉴를 조회한다.",
            ],
        },
        environ=runtime_env,
        requester=requester,
    )
    items = response.get("data")
    if not isinstance(items, list) or len(items) != 2:
        raise EmbeddingRevisionABError("S20QK_EMBEDDING_RESPONSE_INVALID")
    indices: list[int] = []
    dimensions: list[int] = []
    finite_vectors = True
    for item in items:
        if not isinstance(item, Mapping):
            raise EmbeddingRevisionABError("S20QK_EMBEDDING_RESPONSE_INVALID")
        index = item.get("index")
        vector = item.get("embedding")
        if not isinstance(index, int) or isinstance(index, bool):
            raise EmbeddingRevisionABError("S20QK_EMBEDDING_RESPONSE_INVALID")
        if not isinstance(vector, list) or not vector:
            raise EmbeddingRevisionABError("S20QK_EMBEDDING_RESPONSE_INVALID")
        indices.append(index)
        dimensions.append(len(vector))
        finite_vectors = finite_vectors and all(
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in vector
        )
    return {
        "served_model_name": config.model_name,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "request_shape": config.request_shape,
        "response_model_revision": response.get("model_revision"),
        "response_deployment_id": response.get("deployment_id"),
        "item_count": len(items),
        "indices": indices,
        "vector_dimension": dimensions[0],
        "consistent_dimension": len(set(dimensions)) == 1,
        "finite_vectors": finite_vectors,
        "raw_text_persisted": False,
        "embedding_vector_persisted": False,
    }


def _compare_profiles(env: Mapping[str, str]) -> dict[str, Any]:
    _, evidence_a = _read_json(_required_path(env, PROFILE_A_PATH_ENV))
    _, evidence_b = _read_json(_required_path(env, PROFILE_B_PATH_ENV))
    return compare_embedding_revision_profiles(
        _profile_payload(evidence_a),
        _profile_payload(evidence_b),
    )


def _profile_payload(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    if evidence.get("evidence_schema_version") != SCHEMA_VERSION:
        return evidence
    payload = evidence.get("result")
    if (
        evidence.get("status") != "PASS"
        or evidence.get("mode") != "PROFILE"
        or not isinstance(payload, Mapping)
    ):
        raise EmbeddingRevisionABError("S20QK_PROFILE_EVIDENCE_NOT_ADMITTED")
    return payload


def _required_path(env: Mapping[str, str], key: str) -> Path:
    value = env.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingRevisionABError(f"S20QK_{key}_REQUIRED")
    return Path(value.strip())


def _read_json(path: Path) -> tuple[str, Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, Mapping):
        raise TypeError("S20Q-K evidence must be a JSON object")
    return text, value


def _text_hash(value: str) -> str:
    return f"sha256:{sha256_text(value)}"


def _assert_redacted(result: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 4 and value in serialized:
            raise ValueError("S20Q-K evidence contains protected data")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20qk_embedding_revision_ab=skipped reason={SMOKE_ENV}"
    if status == "pass":
        mode = result.get("mode")
        payload = result.get("result")
        if mode == "PROFILE" and isinstance(payload, Mapping):
            calibration = payload.get("calibration")
            decision = (
                calibration.get("status")
                if isinstance(calibration, Mapping)
                else "unknown"
            )
            binding = payload.get("embedding_binding")
            dimension = (
                binding.get("vector_dimension")
                if isinstance(binding, Mapping)
                else "unknown"
            )
            return (
                "gb2_s20qk_embedding_revision_ab=pass "
                f"mode=profile slot={payload.get('slot')} "
                f"dimension={dimension} decision={decision}"
            )
        decision = payload.get("decision") if isinstance(payload, Mapping) else {}
        decision_status = (
            decision.get("status") if isinstance(decision, Mapping) else "unknown"
        ) or "unknown"
        return (
            "gb2_s20qk_embedding_revision_ab=pass "
            f"mode=compare decision={decision_status}"
        )
    return (
        "gb2_s20qk_embedding_revision_ab=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--slot", choices=("A", "B"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--profile-a", type=Path)
    parser.add_argument("--profile-b", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.mode:
        env[MODE_ENV] = args.mode
    if args.slot:
        env[SLOT_ENV] = args.slot
    for key, value in (
        (SOURCE_PATH_ENV, args.source),
        (ARTIFACT_PATH_ENV, args.artifact),
        (PROFILE_A_PATH_ENV, args.profile_a),
        (PROFILE_B_PATH_ENV, args.profile_b),
    ):
        if value is not None:
            env[key] = str(value)
    result = run_gb2_s20qk_embedding_revision_ab(env)
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
