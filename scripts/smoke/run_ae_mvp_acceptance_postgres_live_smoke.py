#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.mvp_operations_handoff import (  # noqa: E402
    build_ae_mvp_operations_handoff_candidate,
    verify_ae_mvp_operations_handoff,
)
from nex_runtime import build_engine, load_env_file  # noqa: E402
import run_ae_web_grounded_generation_playwright_postgres_smoke as s109  # noqa: E402


SCHEMA_VERSION = "ae_mvp_acceptance_postgres_live_smoke.v1"
SMOKE_ENV = "NEX_AE_MVP_ACCEPTANCE_POSTGRES_LIVE_SMOKE"
AE_DATABASE_ENV = s109.AE_DATABASE_ENV
CX_DATABASE_ENV = s109.CX_DATABASE_ENV
EXPECTED_IDENTITIES = {
    "ae": {"database": s109.AE_DATABASE, "role": s109.AE_ROLE},
    "cx": {"database": s109.CX_DATABASE, "role": s109.CX_ROLE},
}
EXPECTED_MODELS = dict(s109.EXPECTED_MODELS)
PROTECTED_ENV_KEYS = tuple(s109.PROTECTED_ENV_KEYS)

LiveRunner = Callable[[Mapping[str, str]], dict[str, Any]]
ResidueReader = Callable[[str, str], dict[str, Any]]


def run_ae_mvp_acceptance_postgres_live_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    live_runner: LiveRunner | None = None,
    residue_reader: ResidueReader | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1099",
            "requirement": "S110",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    ae_url = str(env.get(AE_DATABASE_ENV) or "")
    cx_url = str(env.get(CX_DATABASE_ENV) or "")
    if not ae_url or not cx_url:
        return _failure("database_url_missing", "Both test database URLs are required.")

    effective_env = {**env, s109.SMOKE_ENV: "1", s109.PROFILE_ENV: "test"}
    try:
        source = (live_runner or _run_s109_live)(effective_env)
        if source.get("status") != "PASS":
            return _failure(
                "s109_live_smoke_failed",
                str(source.get("failure_code") or source.get("status") or "unknown"),
            )
        residue = (residue_reader or read_s109_probe_residue)(ae_url, cx_url)
        observed_at = _normalize_now(now)
        candidate = build_ae_mvp_operations_handoff_candidate(
            generated_at=observed_at
        )
        evidence = _build_evidence(
            source=source,
            residue=residue,
            candidate=candidate,
            observed_at=observed_at,
        )
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except (OSError, SQLAlchemyError, RuntimeError, ValueError) as exc:
        result = _failure("acceptance_live_smoke_failed", exc.__class__.__name__)
        assert_evidence_redacted(result, effective_env)
        return result


def _run_s109_live(env: Mapping[str, str]) -> dict[str, Any]:
    return s109.run_ae_web_grounded_generation_playwright_postgres_smoke(env)


def _build_evidence(
    *,
    source: Mapping[str, Any],
    residue: Mapping[str, Any],
    candidate: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    identities = _mapping(source.get("database_identity"))
    providers = _mapping(source.get("provider_observation"))
    browser = _mapping(source.get("browser_observation"))
    persistence = _mapping(source.get("persistence_observation"))
    source_checks = _mapping(source.get("checks"))
    provider_models = {
        capability: _mapping(providers.get(capability)).get("model")
        for capability in EXPECTED_MODELS
    }
    failed_calls = sum(
        _nonnegative_int(_mapping(providers.get(capability)).get("failure_count"))
        for capability in EXPECTED_MODELS
    )
    successful_capabilities = sum(
        _nonnegative_int(_mapping(providers.get(capability)).get("success_count"))
        >= 1
        for capability in EXPECTED_MODELS
    )
    residue_counts = _mapping(residue.get("counts"))
    total_residue = residue.get("total_rows")
    candidate_verification = verify_ae_mvp_operations_handoff(candidate)
    timestamp = _timestamp(observed_at)
    checks = {
        "source_live_smoke_passed": source.get("status") == "PASS",
        "source_checks_passed": bool(source_checks) and all(source_checks.values()),
        "actual_test_postgres_proven": (
            source.get("actual_postgres") is True
            and identities == EXPECTED_IDENTITIES
        ),
        "live_provider_models_frozen": provider_models == EXPECTED_MODELS,
        "all_live_capabilities_succeeded": successful_capabilities == 3,
        "live_provider_failures_absent": failed_calls == 0,
        "verified_response_displayed": browser.get("display_mode")
        == "VERIFIED_RESPONSE",
        "durable_terminal_states_proven": (
            persistence.get("ae_status") == "COMPLETED"
            and persistence.get("retrieval_status") == "READY"
            and persistence.get("generation_status") == "COMPLETED"
            and persistence.get("job_status") == "SUCCEEDED"
        ),
        "browser_server_secret_absent": source_checks.get(
            "browser_received_no_server_secret"
        )
        is True,
        "probe_residue_zero": (
            residue.get("status") == "PASS"
            and isinstance(total_residue, int)
            and total_residue == 0
            and bool(residue_counts)
        ),
        "operations_handoff_candidate_verified": (
            candidate_verification.get("status") == "VERIFIED"
            and candidate.get("manifest_status") == "SEALED"
            and candidate.get("target_service") == "nex-ag"
        ),
    }
    gate_evidence = {
        "postgres_smoke": {
            "status": "PASS" if checks["actual_test_postgres_proven"] and checks["probe_residue_zero"] else "FAIL",
            "observed_at": timestamp,
            "backend": "postgresql",
            "databases": [s109.AE_DATABASE, s109.CX_DATABASE],
            "zero_residue": checks["probe_residue_zero"],
        },
        "live_grounded_generation": {
            "status": "PASS" if all(
                checks[name]
                for name in (
                    "live_provider_models_frozen",
                    "all_live_capabilities_succeeded",
                    "live_provider_failures_absent",
                    "verified_response_displayed",
                    "browser_server_secret_absent",
                )
            ) else "FAIL",
            "observed_at": timestamp,
            "provider_models": provider_models,
            "failed_calls": failed_calls,
            "browser_engine": "chromium",
            "display_state": browser.get("display_mode"),
            "server_secret_header": False,
        },
        "operations_handoff": {
            "status": "PASS" if checks["operations_handoff_candidate_verified"] else "FAIL",
            "observed_at": timestamp,
            "target_service": candidate.get("target_service"),
            "manifest_status": candidate.get("manifest_status"),
        },
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1099",
        "requirement": "S110",
        "status": "PASS" if not failed_checks else "FAIL",
        "failure_code": None if not failed_checks else "acceptance_checks_failed",
        "actual_postgres": source.get("actual_postgres") is True,
        "database_identity": dict(identities),
        "browser_observation": {
            "engine": "chromium",
            "display_state": browser.get("display_mode"),
        },
        "provider_observation": {
            "models": provider_models,
            "successful_capability_count": successful_capabilities,
            "failed_call_count": failed_calls,
        },
        "persistence_observation": {
            "ae_status": persistence.get("ae_status"),
            "retrieval_status": persistence.get("retrieval_status"),
            "generation_status": persistence.get("generation_status"),
            "job_status": persistence.get("job_status"),
        },
        "residue_observation": {
            "counts": dict(residue_counts),
            "total_rows": total_residue,
        },
        "handoff_observation": {
            "target_service": candidate.get("target_service"),
            "manifest_status": candidate.get("manifest_status"),
            "verification_status": candidate_verification.get("status"),
        },
        "acceptance_gate_evidence": gate_evidence,
        "checks": checks,
        "failed_checks": failed_checks,
    }


def read_s109_probe_residue(ae_database_url: str, cx_database_url: str) -> dict[str, Any]:
    ae_engine = build_engine(ae_database_url)
    cx_engine = build_engine(cx_database_url)
    try:
        counts = {
            "ae_chat_interactions": _count(
                ae_engine,
                "SELECT COUNT(*) FROM ae_chat_interactions WHERE user_id = :owner_id",
            ),
            "ae_workspaces": _count(
                ae_engine,
                "SELECT COUNT(*) FROM ae_workspaces WHERE owner_user_id = :owner_id",
            ),
            "cx_generation_executions": _count(
                cx_engine,
                "SELECT COUNT(*) FROM cx_generation_executions WHERE owner_subject_ref_id = :owner_id",
            ),
            "cx_generation_admissions": _count(
                cx_engine,
                "SELECT COUNT(*) FROM cx_gen_admissions WHERE owner_subject_ref_id = :owner_id",
            ),
            "cx_generation_jobs": _count(
                cx_engine,
                "SELECT COUNT(*) FROM service_jobs WHERE job_type = 'cx.grounded-generation.execute' AND subject_type = 'oa.user' AND subject_id = :owner_id",
            ),
        }
        total = sum(counts.values())
        return {"status": "PASS" if total == 0 else "FAIL", "counts": counts, "total_rows": total}
    finally:
        ae_engine.dispose()
        cx_engine.dispose()


def _count(engine: Any, statement: str) -> int:
    with engine.connect() as connection:
        value = connection.execute(text(statement), {"owner_id": s109.OWNER_ID}).scalar_one()
    return int(value)


def assert_evidence_redacted(
    evidence: Mapping[str, Any], environ: Mapping[str, str]
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    for marker in (s109.SOURCE_TEXT, s109.LOGIN_PASSWORD, "postgresql+psycopg://"):
        if marker in serialized:
            raise ValueError("AE MVP live evidence contains protected content.")
    for key in PROTECTED_ENV_KEYS:
        fragment = s109._secret_fragment(key, environ.get(key))
        if fragment and fragment in serialized:
            raise ValueError("AE MVP live evidence contains a protected value.")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1099",
        "requirement": "S110",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _normalize_now(value: datetime | None) -> datetime:
    observed = datetime.now(UTC) if value is None else value
    if observed.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return observed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status == "skipped":
        return f"ae_mvp_acceptance_live=skipped reason={SMOKE_ENV}"
    checks = _mapping(evidence.get("checks"))
    providers = _mapping(evidence.get("provider_observation"))
    residue = _mapping(evidence.get("residue_observation"))
    return (
        f"ae_mvp_acceptance_live={status} "
        f"checks={sum(bool(item) for item in checks.values())}/{len(checks)} "
        f"providers={providers.get('successful_capability_count', 0)}/3 "
        f"display={_mapping(evidence.get('browser_observation')).get('display_state', 'not-run')} "
        f"residue={residue.get('total_rows', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected AE MVP PostgreSQL, DGX, and Playwright acceptance smoke."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_mvp_acceptance_postgres_live_smoke()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
