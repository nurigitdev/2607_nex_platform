#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_observability_collector import (  # noqa: E402
    RuntimeObservationCollectionError,
    collect_runtime_observations,
)
from nex_mo.runtime_observability_plan import (  # noqa: E402
    OBSERVABILITY_MODE_ENV,
    SSH_TARGET_ENV,
    build_runtime_observation_plan,
)
from nex_mo.runtime_observability_policy import (  # noqa: E402
    runtime_observation_thresholds,
)


ACTIVATION_ENV = "NEX_MO_RUNTIME_OBSERVABILITY_LIVE_SMOKE"
EVIDENCE_SCHEMA_VERSION = "mo_runtime_observability_live_evidence.v1"
RuntimeCollector = Callable[..., Any]


def run_mo_runtime_observability_live_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    collector: RuntimeCollector = collect_runtime_observations,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    target_configured = bool(env.get(SSH_TARGET_ENV))
    if env.get(ACTIVATION_ENV) != "1":
        return _evidence(
            status="SKIPPED",
            stage_status={"activation": "SKIPPED"},
            target_configured=target_configured,
            checks={},
            snapshot=None,
            issues=[{"stage": "activation", "error_code": "live_smoke_not_enabled"}],
        )

    effective_env = dict(env)
    effective_env[OBSERVABILITY_MODE_ENV] = "live"
    try:
        plan = build_runtime_observation_plan(effective_env)
        thresholds = runtime_observation_thresholds(effective_env)
    except ValueError:
        return _evidence(
            status="FAIL",
            stage_status={"activation": "PASS", "configuration": "FAIL"},
            target_configured=target_configured,
            checks={},
            snapshot=None,
            issues=[
                {"stage": "configuration", "error_code": "live_configuration_invalid"}
            ],
        )

    try:
        snapshot = collector(
            plan,
            ttl_seconds=30,
            thresholds=thresholds,
        ).to_wire()
    except RuntimeObservationCollectionError as exc:
        return _collection_failure(exc.error_code, target_configured=target_configured)
    except Exception:
        return _collection_failure(
            "collector_unexpected_failure",
            target_configured=target_configured,
        )

    if not isinstance(snapshot, dict):
        return _collection_failure(
            "collector_payload_invalid",
            target_configured=target_configured,
        )

    models = snapshot.get("models")
    model_items = (
        [item for item in models if isinstance(item, dict)]
        if isinstance(models, list)
        else []
    )
    expected_models = {
        target.provider_capability: target.model_revision for target in plan.targets
    }
    private_values = _private_values(env)
    serialized_snapshot = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    checks = {
        "live_mode_observed": snapshot.get("observation_mode") == "live",
        "aggregate_runtime_healthy": snapshot.get("runtime_status") == "HEALTHY",
        "all_capabilities_observed": {
            item.get("provider_capability") for item in model_items
        }
        == set(expected_models),
        "one_process_per_capability": len(model_items) == 3
        and all(item.get("process_count") == 1 for item in model_items),
        "expected_models_observed": len(model_items) == 3
        and all(
            expected_models.get(item.get("provider_capability"))
            == item.get("model_revision")
            for item in model_items
        ),
        "requested_precision_matched": len(model_items) == 3
        and all(item.get("precision_status") == "MATCH" for item in model_items),
        "gpu_runtime_present": len(model_items) == 3
        and all((item.get("gpu_count") or 0) >= 1 for item in model_items),
        "gpu_metrics_complete": len(model_items) == 3
        and all(
            all(
                item.get(field) is not None
                for field in (
                    "gpu_memory_used_mib",
                    "gpu_memory_total_mib",
                    "gpu_utilization_percent",
                    "gpu_temperature_c",
                )
            )
            for item in model_items
        ),
        "private_runtime_values_absent": not any(
            value in serialized_snapshot for value in private_values
        ),
    }
    passed = all(checks.values())
    safe_snapshot = snapshot if checks["private_runtime_values_absent"] else None
    return _evidence(
        status="PASS" if passed else "FAIL",
        stage_status={
            "activation": "PASS",
            "configuration": "PASS",
            "collection": "PASS",
            "assertions": "PASS" if passed else "FAIL",
        },
        target_configured=target_configured,
        checks=checks,
        snapshot=safe_snapshot,
        issues=[]
        if passed
        else [
            {"stage": "assertions", "error_code": "live_runtime_assertion_failed"}
        ],
    )


def _private_values(environ: Mapping[str, str]) -> tuple[str, ...]:
    private_markers = ("API_KEY", "PASSWORD", "SECRET", "TOKEN")
    values = [environ.get(SSH_TARGET_ENV, "")]
    values.extend(
        value
        for key, value in environ.items()
        if value and any(marker in key.upper() for marker in private_markers)
    )
    return tuple(value for value in values if value)


def _collection_failure(
    error_code: str,
    *,
    target_configured: bool,
) -> dict[str, Any]:
    return _evidence(
        status="FAIL",
        stage_status={
            "activation": "PASS",
            "configuration": "PASS",
            "collection": "FAIL",
        },
        target_configured=target_configured,
        checks={},
        snapshot=None,
        issues=[{"stage": "collection", "error_code": error_code}],
    )


def _evidence(
    *,
    status: str,
    stage_status: dict[str, str],
    target_configured: bool,
    checks: dict[str, bool],
    snapshot: dict[str, Any] | None,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    raw_models = snapshot.get("models", []) if snapshot else []
    models = [item for item in raw_models if isinstance(item, dict)]
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "slice": "1170",
        "requirement": "S117",
        "status": status,
        "stage_status": stage_status,
        "target_configured": target_configured,
        "checks": checks,
        "summary": {
            "model_count": len(models),
            "healthy_count": sum(
                item.get("runtime_status") == "HEALTHY" for item in models
            ),
            "precision_match_count": sum(
                item.get("precision_status") == "MATCH" for item in models
            ),
            "gpu_observed_count": sum((item.get("gpu_count") or 0) >= 1 for item in models),
        },
        "snapshot": snapshot,
        "issues": issues,
        "redaction": {
            "status": "PASS" if snapshot is not None or status == "SKIPPED" else "ENFORCED",
            "excluded": [
                "ssh_target",
                "process_id",
                "process_command_line",
                "model_path",
                "api_key",
                "credential",
            ],
        },
        "next_slice": "1171" if status == "PASS" else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"mo_runtime_observability_live_smoke=skipped reason={ACTIVATION_ENV}"
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observability_live_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"models={summary.get('model_count', 0)}/3 "
        f"healthy={summary.get('healthy_count', 0)}/3 "
        f"precision={summary.get('precision_match_count', 0)}/3 "
        f"gpu={summary.get('gpu_observed_count', 0)}/3 "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def write_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    resolved = output_path.expanduser().resolve()
    if not resolved.is_relative_to(Path("/tmp").resolve()):
        raise ValueError("protected runtime evidence output must be below /tmp")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect protected DGX GPU/model runtime observability evidence."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observability_live_smoke()
    if args.output:
        write_evidence(args.output, evidence)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
