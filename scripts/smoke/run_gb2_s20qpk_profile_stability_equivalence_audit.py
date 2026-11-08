#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "quality",
):
    sys.path.insert(0, str(path))

from check_retrieval_calibration_v4_dataset import DEFAULT_DATASET_PATH
from nex_cx.retrieval_answer_support_nested_selection import (
    build_answer_support_nested_samples,
)
from nex_cx.retrieval_answer_support_profile_equivalence import (
    audit_answer_support_profile_equivalence,
)

SCHEMA_VERSION = "gb2_s20qpk_profile_stability_equivalence_audit.v1"
SMOKE_ENV = "NEX_GB2_S20QPK_PROFILE_EQUIVALENCE_AUDIT"
PROFILE_ENV = "NEX_GB2_S20QPK_PROFILE"
P_I_SOURCE_ENV = "NEX_GB2_S20QPK_P_I_EVIDENCE"
P_J_SOURCE_ENV = "NEX_GB2_S20QPK_P_J_EVIDENCE"
P_I_SOURCE = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpi_answer_support_calibration_collection.json"
)
P_J_SOURCE = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpj_nested_answer_support_calibration.json"
)
DATA = ROOT / "scripts" / "smoke" / "data"
NESTED_DESIGN_PATH = DATA / "s136_answer_support_nested_calibration_v1_design.json"
AUDIT_DESIGN_PATH = (
    DATA / "s136_answer_support_profile_equivalence_audit_v1_design.json"
)
FOLD_PATH = DATA / "s136_retrieval_package_calibration_v4_folds.json"
OUTPUT_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpk_profile_stability_equivalence_audit.json"
)

SampleBuilder = Callable[
    [Mapping[str, Any], Sequence[Mapping[str, Any]]], list[dict[str, Any]]
]
Auditor = Callable[..., dict[str, Any]]


def run_gb2_s20qpk_profile_stability_equivalence_audit(
    environ: Mapping[str, str] | None = None,
    *,
    p_i_source: Mapping[str, Any] | None = None,
    p_j_source: Mapping[str, Any] | None = None,
    sample_builder: SampleBuilder = build_answer_support_nested_samples,
    auditor: Auditor = audit_answer_support_profile_equivalence,
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
    if p_i_source is None:
        loaded = _load_source(Path(env.get(P_I_SOURCE_ENV, str(P_I_SOURCE))), "p_i")
        if "failure_code" in loaded:
            return loaded
        p_i_source = loaded
    if p_j_source is None:
        loaded = _load_source(Path(env.get(P_J_SOURCE_ENV, str(P_J_SOURCE))), "p_j")
        if "failure_code" in loaded:
            return loaded
        p_j_source = loaded

    try:
        dataset = _load(DEFAULT_DATASET_PATH)
        nested_design = _load(NESTED_DESIGN_PATH)
        audit_design = _load(AUDIT_DESIGN_PATH)
        fold_plan = _load(FOLD_PATH)
        collection = _mapping(p_i_source.get("collection"), "P-I collection")
        selection = _mapping(p_j_source.get("selection"), "P-J selection")
        samples = sample_builder(collection, dataset["cases"])
        audit = auditor(
            samples,
            nested_design=nested_design,
            fold_plan=fold_plan,
            p_j_selection=selection,
            audit_design=audit_design,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "profile_equivalence_audit_failed",
            detail={"exception": exc.__class__.__name__},
        )

    p_i_dataset = _mapping(collection.get("dataset"), "P-I dataset")
    p_j_binding = _mapping(selection.get("binding"), "P-J binding")
    checks = {
        "p_i_evidence_passed": p_i_source.get("status") == "PASS",
        "p_j_evidence_passed": p_j_source.get("status") == "PASS",
        "p_j_remains_no_admissible_profile": selection.get("status")
        == "NO_ADMISSIBLE_PROFILE",
        "source_collection_binding_matches": (
            p_j_binding.get("source_collection_hash")
            == collection.get("collection_hash")
            == audit.get("source_binding", {}).get("collection_hash")
        ),
        "calibration_scope_complete": audit.get("dataset")
        == {
            "partition": "CALIBRATION",
            "scenario_count": 80,
            "package_count": 160,
        },
        "audit_completed": audit.get("status") == "DIAGNOSED",
        "equivalence_not_authorized": audit.get("equivalence_family_authorized")
        is False,
        "holdout_remained_sealed": (
            selection.get("holdout_access_permitted") is False
            and p_i_dataset.get("holdout_status") == "SEALED_NOT_ACCESSED"
            and audit.get("next_contract", {}).get("holdout_access_permitted")
            is False
        ),
        "runtime_activation_prohibited": audit.get("next_contract", {}).get(
            "runtime_activation_permitted"
        )
        is False,
    }
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-K",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": audit.get("decision"),
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "source_collection_hash": collection.get("collection_hash"),
        "source_selection_hash": selection.get("selection_hash"),
        "audit": audit,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    try:
        _assert_text_free(result, dataset)
    except ValueError:
        return _failure("protected_evidence_contains_source_text")
    return result


def _load_source(path: Path, source_id: str) -> dict[str, Any]:
    if not path.is_file():
        return _failure(f"{source_id}_evidence_missing")
    try:
        return _load(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            f"{source_id}_evidence_invalid",
            detail={"exception": exc.__class__.__name__},
        )


def _assert_text_free(evidence: object, dataset: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Dataset v4 cases are invalid")
    protected = [str(case["query"]) for case in cases]
    protected.extend(
        str(candidate["text"])
        for case in cases
        for candidate in case["candidates"]
    )
    if any(value in serialized for value in protected):
        raise ValueError("P-K evidence contains source text")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("evidence must be a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


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
        audit = result.get("audit")
        audit = audit if isinstance(audit, Mapping) else {}
        empirical = audit.get("empirical_equivalence")
        empirical = empirical if isinstance(empirical, Mapping) else {}
        semantic = audit.get("semantic_equivalence")
        semantic = semantic if isinstance(semantic, Mapping) else {}
        semantic_checks = semantic.get("checks")
        semantic_checks = semantic_checks if isinstance(semantic_checks, Mapping) else {}
        return (
            "gb2_s20qpk_profile_equivalence_audit=pass "
            f"decision={audit.get('decision')} "
            f"ordering={empirical.get('score_ordering_agreement_rate')} "
            f"oof_disagreement={empirical.get('oof_decision_disagreement_rate')} "
            f"semantic_equivalent={all(semantic_checks.values())} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpk_profile_equivalence_audit=skipped"
    return (
        "gb2_s20qpk_profile_equivalence_audit=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpk_profile_stability_equivalence_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        f"{json.dumps(result, indent=2, sort_keys=True)}\n", encoding="utf-8"
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
