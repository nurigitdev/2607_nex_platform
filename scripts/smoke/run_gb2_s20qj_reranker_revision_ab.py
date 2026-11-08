#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_reranker_revision_ab import (
    RerankerRevisionABError,
    build_reranker_revision_profile,
    compare_reranker_revision_profiles,
)
from nex_runtime.semantic_hashes import sha256_text

SCHEMA_VERSION = "gb2_s20qj_reranker_revision_ab.v1"
SMOKE_ENV = "NEX_GB2_S20QJ_RERANKER_REVISION_AB"
MODE_ENV = "NEX_GB2_S20QJ_MODE"
SLOT_ENV = "NEX_GB2_S20QJ_PROFILE_SLOT"
SOURCE_PATH_ENV = "NEX_GB2_S20QJ_SOURCE_EVIDENCE_PATH"
REPEATABILITY_PATH_ENV = "NEX_GB2_S20QJ_REPEATABILITY_EVIDENCE_PATH"
REVISION_PATH_ENV = "NEX_GB2_S20QJ_REVISION_EVIDENCE_PATH"
PROFILE_A_PATH_ENV = "NEX_GB2_S20QJ_PROFILE_A_PATH"
PROFILE_B_PATH_ENV = "NEX_GB2_S20QJ_PROFILE_B_PATH"
MODES = frozenset({"PROFILE", "COMPARE"})
PROTECTED_ENV_KEYS = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_CX_TEST_DATABASE_URL",
)


def run_gb2_s20qj_reranker_revision_ab(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    mode = str(env.get(MODE_ENV, "")).strip().upper()
    try:
        if mode not in MODES:
            raise RerankerRevisionABError("S20QJ_MODE_INVALID")
        if mode == "PROFILE":
            result = _build_profile(env)
        else:
            result = _compare_profiles(env)
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
        RerankerRevisionABError,
    ) as exc:
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "mode": mode or None,
            "failure_code": getattr(exc, "error_code", "S20QJ_EXECUTION_FAILED"),
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(evidence, env)
    return evidence


def _build_profile(env: Mapping[str, str]) -> dict[str, Any]:
    source_text, source = _read_json(_required_path(env, SOURCE_PATH_ENV))
    repeatability_text, repeatability = _read_json(
        _required_path(env, REPEATABILITY_PATH_ENV)
    )
    revision_text, revision = _read_json(_required_path(env, REVISION_PATH_ENV))
    return build_reranker_revision_profile(
        source,
        repeatability=repeatability,
        revision=revision,
        slot=str(env.get(SLOT_ENV, "")),
        source_evidence_sha256=_text_hash(source_text),
        repeatability_evidence_sha256=_text_hash(repeatability_text),
        revision_evidence_sha256=_text_hash(revision_text),
    )


def _compare_profiles(env: Mapping[str, str]) -> dict[str, Any]:
    _, evidence_a = _read_json(_required_path(env, PROFILE_A_PATH_ENV))
    _, evidence_b = _read_json(_required_path(env, PROFILE_B_PATH_ENV))
    profile_a = _profile_payload(evidence_a)
    profile_b = _profile_payload(evidence_b)
    return compare_reranker_revision_profiles(profile_a, profile_b)


def _profile_payload(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    if evidence.get("evidence_schema_version") != SCHEMA_VERSION:
        return evidence
    payload = evidence.get("result")
    if (
        evidence.get("status") != "PASS"
        or evidence.get("mode") != "PROFILE"
        or not isinstance(payload, Mapping)
    ):
        raise RerankerRevisionABError("S20QJ_PROFILE_EVIDENCE_NOT_ADMITTED")
    return payload


def _required_path(env: Mapping[str, str], key: str) -> Path:
    value = env.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RerankerRevisionABError(f"S20QJ_{key}_REQUIRED")
    return Path(value.strip())


def _read_json(path: Path) -> tuple[str, Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, Mapping):
        raise TypeError("S20Q-J evidence must be a JSON object")
    return text, value


def _text_hash(value: str) -> str:
    return f"sha256:{sha256_text(value)}"


def _assert_redacted(result: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 4 and value in serialized:
            raise ValueError("S20Q-J evidence contains protected data")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20qj_reranker_revision_ab=skipped reason={SMOKE_ENV}"
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
            return (
                "gb2_s20qj_reranker_revision_ab=pass "
                f"mode=profile slot={payload.get('slot')} decision={decision}"
            )
        decision = payload.get("decision") if isinstance(payload, Mapping) else {}
        decision_status = (
            decision.get("status") if isinstance(decision, Mapping) else "unknown"
        ) or "unknown"
        return (
            "gb2_s20qj_reranker_revision_ab=pass "
            f"mode=compare decision={decision_status}"
        )
    return (
        "gb2_s20qj_reranker_revision_ab=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--slot", choices=("A", "B"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--repeatability", type=Path)
    parser.add_argument("--revision", type=Path)
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
        (REPEATABILITY_PATH_ENV, args.repeatability),
        (REVISION_PATH_ENV, args.revision),
        (PROFILE_A_PATH_ENV, args.profile_a),
        (PROFILE_B_PATH_ENV, args.profile_b),
    ):
        if value is not None:
            env[key] = str(value)
    result = run_gb2_s20qj_reranker_revision_ab(env)
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
