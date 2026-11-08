from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nex_runtime import admit_model_calibration_package_dataset_v4
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, sha256_text

from nex_cx.retrieval_calibration_design import (
    admit_retrieval_calibration_v4_design,
)

NESTED_FOLD_PLAN_SCHEMA_VERSION = "cx_retrieval_nested_fold_plan.v1"


@dataclass
class NestedFoldAssignmentError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_retrieval_calibration_nested_fold_plan(
    dataset_payload: Mapping[str, Any],
    design_payload: Mapping[str, Any],
) -> dict[str, Any]:
    admitted_dataset = admit_model_calibration_package_dataset_v4(dataset_payload)
    admitted_design = admit_retrieval_calibration_v4_design(design_payload)
    dataset = admitted_dataset.dataset
    design = admitted_design.design
    if (
        dataset["dataset_schema_version"]
        != design["dataset"]["target_schema_version"]
        or dataset["dataset_id"] != design["dataset"]["target_dataset_id"]
    ):
        raise _invalid("dataset and design binding mismatch")

    selection = design["selection_protocol"]
    calibration = _calibration_scenarios(dataset["cases"])
    outer_fold_count = int(selection["outer_fold_count"])
    inner_fold_count = int(selection["inner_fold_count"])
    seed = str(selection["assignment_seed"])
    outer_groups = _assign_stratified_groups(
        calibration,
        fold_count=outer_fold_count,
        target_size=int(selection["outer_validation_scenarios_per_fold"]),
        seed=seed,
        namespace="outer",
    )
    outer_folds: list[dict[str, Any]] = []
    all_scenarios = {row["scenario_id"] for row in calibration}
    for outer_index, outer_validation in enumerate(outer_groups):
        outer_validation_ids = {row["scenario_id"] for row in outer_validation}
        outer_training = [
            row for row in calibration if row["scenario_id"] not in outer_validation_ids
        ]
        inner_groups = _assign_stratified_groups(
            outer_training,
            fold_count=inner_fold_count,
            target_size=int(selection["inner_validation_scenarios_per_fold"]),
            seed=seed,
            namespace=f"inner:{outer_index}",
        )
        _require_exact_partition(
            inner_groups,
            expected={row["scenario_id"] for row in outer_training},
            field=f"outer fold {outer_index} inner",
        )
        outer_folds.append(
            {
                "fold_index": outer_index,
                "training_scenario_count": len(outer_training),
                "validation_scenario_count": len(outer_validation),
                "validation_scenario_ids": sorted(outer_validation_ids),
                "validation_strata": _strata_counts(outer_validation),
                "inner_folds": [
                    {
                        "fold_index": inner_index,
                        "training_scenario_count": (
                            len(outer_training) - len(inner_validation)
                        ),
                        "validation_scenario_count": len(inner_validation),
                        "validation_scenario_ids": sorted(
                            row["scenario_id"] for row in inner_validation
                        ),
                        "validation_strata": _strata_counts(inner_validation),
                    }
                    for inner_index, inner_validation in enumerate(inner_groups)
                ],
            }
        )
    _require_exact_partition(outer_groups, expected=all_scenarios, field="outer")
    result = {
        "fold_plan_schema_version": NESTED_FOLD_PLAN_SCHEMA_VERSION,
        "status": "ASSIGNED",
        "dataset": {
            "dataset_id": admitted_dataset.manifest["dataset_id"],
            "dataset_sha256": admitted_dataset.manifest["dataset_sha256"],
            "calibration_scenario_count": len(calibration),
            "holdout_scenario_count": admitted_dataset.manifest[
                "partition_scenario_counts"
            ]["HOLDOUT"],
        },
        "design": {
            "design_id": admitted_design.manifest["design_id"],
            "design_hash": admitted_design.manifest["design_hash"],
        },
        "assignment": {
            "algorithm": selection["assignment_algorithm"],
            "seed": seed,
            "group_key": selection["group_key"],
            "stratification_fields": list(selection["stratification_fields"]),
            "outer_fold_count": outer_fold_count,
            "inner_fold_count": inner_fold_count,
            "outer_folds": outer_folds,
        },
        "checks": {
            "scenario_pair_grouping_preserved": True,
            "outer_partition_exact": True,
            "inner_partitions_exact": True,
            "holdout_excluded": True,
            "query_or_candidate_text_included": False,
        },
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    result["fold_plan_hash"] = semantic_sha256_hash_ref(result)
    return result


def _calibration_scenarios(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows = [
        {
            "scenario_id": str(case["scenario_id"]),
            "domain": str(case["domain"]),
            "language_profile": str(case["language_profile"]),
        }
        for case in cases
        if case["partition"] == "CALIBRATION" and case["expected_ready"] is True
    ]
    if len(rows) != 80:
        raise _invalid("calibration scenario count")
    return sorted(rows, key=lambda row: row["scenario_id"])


def _assign_stratified_groups(
    scenarios: Sequence[Mapping[str, str]],
    *,
    fold_count: int,
    target_size: int,
    seed: str,
    namespace: str,
) -> list[list[dict[str, str]]]:
    if (
        fold_count <= 0
        or target_size <= 0
        or len(scenarios) != fold_count * target_size
    ):
        raise _invalid(f"{namespace} fold geometry")
    strata: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in scenarios:
        strata[(row["domain"], row["language_profile"])].append(dict(row))
    groups: list[list[dict[str, str]]] = [[] for _ in range(fold_count)]
    stratum_counts = [Counter() for _ in range(fold_count)]
    domain_counts = [Counter() for _ in range(fold_count)]
    language_counts = [Counter() for _ in range(fold_count)]
    ordered_strata = sorted(
        strata,
        key=lambda key: (
            -len(strata[key]),
            sha256_text(f"{seed}|{namespace}|stratum|{'|'.join(key)}"),
        ),
    )
    for stratum in ordered_strata:
        rows = sorted(
            strata[stratum],
            key=lambda row: sha256_text(
                f"{seed}|{namespace}|scenario|{row['scenario_id']}"
            ),
        )
        for row in rows:
            candidates = [
                index for index, group in enumerate(groups) if len(group) < target_size
            ]
            selected = min(
                candidates,
                key=lambda index: (
                    domain_counts[index][row["domain"]]
                    + language_counts[index][row["language_profile"]],
                    max(
                        domain_counts[index][row["domain"]],
                        language_counts[index][row["language_profile"]],
                    ),
                    stratum_counts[index][stratum],
                    len(groups[index]),
                    sha256_text(
                        f"{seed}|{namespace}|fold|{index}|{row['scenario_id']}"
                    ),
                    index,
                ),
            )
            groups[selected].append(row)
            stratum_counts[selected][stratum] += 1
            domain_counts[selected][row["domain"]] += 1
            language_counts[selected][row["language_profile"]] += 1
    _rebalance_marginals(groups, seed=seed, namespace=namespace)
    return [sorted(group, key=lambda row: row["scenario_id"]) for group in groups]


def _rebalance_marginals(
    groups: list[list[dict[str, str]]],
    *,
    seed: str,
    namespace: str,
) -> None:
    current_score = _marginal_imbalance_score(groups)
    while current_score:
        best: tuple[
            int,
            str,
            int,
            int,
            int,
            int,
        ] | None = None
        for left_index in range(len(groups)):
            for right_index in range(left_index + 1, len(groups)):
                for left_row_index, left_row in enumerate(groups[left_index]):
                    for right_row_index, right_row in enumerate(groups[right_index]):
                        if (
                            left_row["domain"] == right_row["domain"]
                            and left_row["language_profile"]
                            == right_row["language_profile"]
                        ):
                            continue
                        groups[left_index][left_row_index] = right_row
                        groups[right_index][right_row_index] = left_row
                        score = _marginal_imbalance_score(groups)
                        groups[left_index][left_row_index] = left_row
                        groups[right_index][right_row_index] = right_row
                        if score >= current_score:
                            continue
                        tie_breaker = sha256_text(
                            f"{seed}|{namespace}|rebalance|"
                            f"{left_row['scenario_id']}|{right_row['scenario_id']}"
                        )
                        candidate = (
                            score,
                            tie_breaker,
                            left_index,
                            right_index,
                            left_row_index,
                            right_row_index,
                        )
                        if best is None or candidate < best:
                            best = candidate
        if best is None:
            break
        (
            current_score,
            _,
            left_index,
            right_index,
            left_row_index,
            right_row_index,
        ) = best
        groups[left_index][left_row_index], groups[right_index][right_row_index] = (
            groups[right_index][right_row_index],
            groups[left_index][left_row_index],
        )


def _marginal_imbalance_score(
    groups: Sequence[Sequence[Mapping[str, str]]],
) -> int:
    score = 0
    for field in ("domain", "language_profile"):
        labels = sorted({row[field] for group in groups for row in group})
        for label in labels:
            counts = [sum(row[field] == label for row in group) for group in groups]
            score += max(counts) - min(counts)
    return score


def _require_exact_partition(
    groups: Sequence[Sequence[Mapping[str, str]]],
    *,
    expected: set[str],
    field: str,
) -> None:
    actual = [str(row["scenario_id"]) for group in groups for row in group]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise _invalid(f"{field} partition")


def _strata_counts(rows: Sequence[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    return {
        "domain": dict(sorted(Counter(row["domain"] for row in rows).items())),
        "language_profile": dict(
            sorted(Counter(row["language_profile"] for row in rows).items())
        ),
    }


def _invalid(field: str) -> NestedFoldAssignmentError:
    return NestedFoldAssignmentError(
        "retrieval_calibration_nested_fold.invalid",
        f"Invalid retrieval calibration nested fold assignment: {field}.",
    )
