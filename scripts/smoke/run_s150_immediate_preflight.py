#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_runtime.production_release import (  # noqa: E402
    canonical_digest,
    validate_release_evidence_manifest,
)
from run_s148_mock_notification_delivery import (  # noqa: E402
    run_mock_notification_delivery,
)
from run_s148_observability_postgres import (  # noqa: E402
    run_observability_postgres_smoke,
)
from run_s149_single_host_live_acceptance import (  # noqa: E402
    run_s149_single_host_live_acceptance,
)


ACTIVATION_ENV = "NEX_S150_IMMEDIATE_PREFLIGHT"
PROFILE_ENV = "NEX_S150_IMMEDIATE_PREFLIGHT_PROFILE"
DEFAULT_PROFILE = "test"
DEFAULT_MANIFEST = ROOT / "reports/deployment/s150-release-manifest.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-immediate-preflight.json"
PREFLIGHT_HOURS = 4
PROTECTED_ENV_KEYS = tuple(
    [
        *(f"NEX_{service}_TEST_DATABASE_URL" for service in ("OA", "AE", "CX", "MO", "AG")),
        "NEX_MO_REMOTE_EMBEDDING_API_KEY",
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_RERANKER_API_KEY",
        "NEX_MO_REMOTE_RERANKER_URL",
        "NEX_MO_VLLM_API_KEY",
        "NEX_MO_VLLM_BASE_URL",
    ]
)

LiveRunner = Callable[[Mapping[str, str], Path], Mapping[str, Any]]
ObservabilityRunner = Callable[[dict[str, str]], Mapping[str, Any]]
IncidentRunner = Callable[[], Mapping[str, Any]]


def run_immediate_preflight(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    manifest_path: Path = DEFAULT_MANIFEST,
    output_path: Path = DEFAULT_OUTPUT,
    clock: Callable[[], datetime] | None = None,
    live_runner: LiveRunner | None = None,
    observability_runner: ObservabilityRunner | None = None,
    incident_runner: IncidentRunner | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": f"--execute and {ACTIVATION_ENV}=1 are required",
            "slice": "1500",
            "requirement": "S150",
        }
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")
    manifest = _load_json(manifest_path)
    if validate_release_evidence_manifest(manifest).get("status") != "PASS":
        return _failure("release_manifest_unavailable_or_invalid")
    now = clock or (lambda: datetime.now(UTC))
    started_at = now()
    if started_at.tzinfo is None:
        return _failure("preflight_clock_must_be_timezone_aware")
    try:
        with TemporaryDirectory(prefix="nex-s150-preflight-") as temporary:
            live = dict(
                (live_runner or _run_live)(env, Path(temporary) / "live.json")
            )
        if live.get("status") != "PASS":
            return _nested_failure("single_host_live", live)
        observability = dict(
            (observability_runner or _run_observability)(env)
        )
        if observability.get("status") != "PASS":
            return _nested_failure("observability", observability)
        incident = dict((incident_runner or run_mock_notification_delivery)())
        if incident.get("status") != "PASS":
            return _nested_failure("incident", incident)
        completed_at = now()
        if completed_at.tzinfo is None:
            return _failure("preflight_clock_must_be_timezone_aware")
        result = _evaluate(
            manifest=manifest,
            live=live,
            observability=observability,
            incident=incident,
            started_at=started_at,
            completed_at=completed_at,
        )
        _assert_redacted(result, env)
        if result["status"] == "PASS":
            _write_json(output_path, result)
        return result
    except Exception as exc:  # noqa: BLE001 - protected preflight fails closed
        result = _failure(
            "immediate_preflight_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )
        _assert_redacted(result, env)
        return result


def _run_live(env: Mapping[str, str], report_path: Path) -> Mapping[str, Any]:
    nested = {
        **env,
        "NEX_S149_SINGLE_HOST_LIVE_ACCEPTANCE": "1",
        "NEX_S149_SINGLE_HOST_LIVE_ACCEPTANCE_PROFILE": "test",
    }
    return run_s149_single_host_live_acceptance(
        nested,
        execute=True,
        report_path=report_path,
    )


def _run_observability(env: Mapping[str, str]) -> Mapping[str, Any]:
    nested = {**env, "NEX_AG_OBSERVABILITY_POSTGRES_SMOKE": "1"}
    return run_observability_postgres_smoke(nested)


def _evaluate(
    *,
    manifest: Mapping[str, Any],
    live: Mapping[str, Any],
    observability: Mapping[str, Any],
    incident: Mapping[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    binding = _mapping(live.get("release_binding"))
    live_checks = _mapping(live.get("checks"))
    live_summary = _mapping(live.get("summary"))
    observability_checks = _mapping(observability.get("checks"))
    observability_cleanup = _mapping(observability.get("cleanup"))
    incident_checks = _mapping(incident.get("checks"))
    duration = (completed_at.astimezone(UTC) - started_at.astimezone(UTC)).total_seconds()
    checks = {
        "exact_release_candidate_bound": binding.get("release_candidate_id")
        == manifest.get("release_candidate_id")
        and binding.get("release_set_digest") == manifest.get("release_set_digest"),
        "trust_database_storage_provider_live": all(live_checks.values())
        and live_summary.get("test_database_count") == 5
        and live_summary.get("live_provider_count") == 3,
        "generation_reasoning_disabled": live_checks.get(
            "generation_reasoning_disabled"
        )
        is True,
        "observability_postgres_live": observability.get("status") == "PASS"
        and observability_checks.get("actual_postgresql_backend") is True
        and observability_checks.get("test_database_selected") is True
        and observability_checks.get("migration_recorded") is True,
        "incident_route_rehearsed": incident.get("status") == "PASS"
        and all(incident_checks.values())
        and incident.get("external_activation") == "EXTERNAL_NOT_ACTIVATED",
        "zero_residue": live_summary.get("residue_count") == 0
        and observability_cleanup.get("residue") == 0,
        "preflight_completed_within_window": 0 <= duration <= PREFLIGHT_HOURS * 3600,
        "production_deployment_separate": True,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    observed_at = completed_at.astimezone(UTC)
    result = {
        "evidence_schema_version": "s150_immediate_preflight.v1",
        "slice": "1500",
        "requirement": "S150",
        "status": "PASS" if not failed_checks else "FAIL",
        "failure_code": None if not failed_checks else "s150_immediate_preflight_failed",
        "freshness_class": "IMMEDIATE_PREFLIGHT_4H",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (observed_at + timedelta(hours=PREFLIGHT_HOURS)).isoformat().replace(
            "+00:00", "Z"
        ),
        "release_candidate_id": manifest.get("release_candidate_id"),
        "release_set_digest": manifest.get("release_set_digest"),
        "checks": checks,
        "failed_checks": failed_checks,
        "source_evidence_digests": {
            "single_host_live": canonical_digest(live),
            "observability_postgres": canonical_digest(observability),
            "incident_mock": canonical_digest(incident),
        },
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "test_database_count": 5,
            "live_provider_count": 3,
            "external_notification_status": "EXTERNAL_NOT_ACTIVATED",
            "duration_seconds": round(duration, 3),
        },
        "production_deployment_approved": False,
        "next_slice": "1501" if not failed_checks else "blocked",
    }
    return result


def _nested_failure(boundary: str, nested: Mapping[str, Any]) -> dict[str, Any]:
    return _failure(
        f"{boundary}_preflight_failed",
        {
            "boundary": boundary,
            "nested_status": str(nested.get("status") or "UNKNOWN"),
            "nested_failure_code": str(nested.get("failure_code") or "not_reported"),
        },
    )


def _failure(code: str, diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": "s150_immediate_preflight.v1",
        "slice": "1500",
        "requirement": "S150",
        "status": "FAIL",
        "failure_code": code,
        "production_deployment_approved": False,
        "next_slice": "blocked",
    }
    if diagnostics:
        result["diagnostics"] = dict(diagnostics)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _assert_redacted(evidence: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, sort_keys=True)
    protected = {
        str(env.get(key) or "").strip()
        for key in PROTECTED_ENV_KEYS
        if str(env.get(key) or "").strip()
    }
    if any(value in serialized for value in protected):
        raise ValueError("S150 preflight evidence contains protected value")


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s150_immediate_preflight=skipped"
    if result.get("status") != "PASS":
        return "s150_immediate_preflight=fail"
    summary = _mapping(result.get("summary"))
    return (
        "s150_immediate_preflight=pass "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"databases={summary.get('test_database_count', 0)}/5 "
        f"providers={summary.get('live_provider_count', 0)}/3 "
        "reasoning=disabled incident=mock next=1501"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_immediate_preflight(
        execute=args.execute,
        manifest_path=args.manifest,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
