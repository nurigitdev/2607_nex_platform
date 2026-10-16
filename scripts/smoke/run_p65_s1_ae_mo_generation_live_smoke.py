#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-ae-api"))

from nex_ae_api.mo_generation_client import (  # noqa: E402
    AeMoGenerationClient,
    AeMoGenerationClientError,
    AeMoGenerationConfigurationError,
    build_default_ae_mo_generation_client,
)


ACTIVATION_ENV = "NEX_AE_P65_S1_LIVE_SMOKE"
EVIDENCE_SCHEMA_VERSION = "ae_p65_s1_mo_generation_live_evidence.v1"


def run_p65_s1_ae_mo_generation_live_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    client: AeMoGenerationClient | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return _evidence(
            status="SKIPPED",
            stages={"activation": "SKIPPED"},
            checks={},
            readiness=None,
            generation=None,
            issues=[{"stage": "activation", "error_code": "live_smoke_not_enabled"}],
        )

    try:
        selected_client = client or build_default_ae_mo_generation_client(env)
    except AeMoGenerationConfigurationError as exc:
        return _failure("configuration", exc.error_code)

    suffix = uuid4().hex
    request_id = f"p65-s1-live-{suffix}"
    trace_id = suffix
    try:
        readiness = selected_client.check_required_mode_readiness(
            request_id=f"{request_id}-readiness",
            trace_id=trace_id,
        )
    except AeMoGenerationClientError as exc:
        return _failure("readiness", exc.error_code)
    except Exception:
        return _failure("readiness", "UNEXPECTED_READINESS_FAILURE")

    try:
        result = selected_client.generate_candidate(
            semantic_stage="INTENT",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "Return exactly one JSON object with string fields status "
                        "and contract. Do not include markdown or reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Set status to ok and contract to p65-s1. "
                        "This is a transport acceptance probe."
                    ),
                },
            ),
            request_id=request_id,
            trace_id=trace_id,
        )
    except AeMoGenerationClientError as exc:
        return _failure("generation", exc.error_code)
    except Exception:
        return _failure("generation", "UNEXPECTED_GENERATION_FAILURE")

    try:
        candidate = json.loads(result.output_text)
    except (TypeError, ValueError):
        candidate = None
    checks = {
        "live_generation_route_ready": (
            readiness.provider_mode == "live"
            and readiness.readiness_status == "READY"
            and readiness.source == "active_preflight"
        ),
        "configured_alias_preserved": (
            result.model_profile == readiness.model_profile
        ),
        "model_revision_preserved": result.model_ref == readiness.model_ref,
        "deployment_preserved": result.deployment_id == readiness.deployment_id,
        "structured_json_observed": isinstance(candidate, dict),
        "golden_probe_observed": (
            isinstance(candidate, dict)
            and candidate.get("status") == "ok"
            and candidate.get("contract") == "p65-s1"
        ),
        "output_digest_recorded": (
            len(result.provider_output_sha256) == 64
            and all(
                character in "0123456789abcdef"
                for character in result.provider_output_sha256
            )
            and result.provider_output_size_bytes > 0
        ),
        "correlation_preserved": (
            result.request_id == request_id and result.trace_id == trace_id
        ),
    }
    passed = all(checks.values())
    return _evidence(
        status="PASS" if passed else "FAIL",
        stages={
            "activation": "PASS",
            "configuration": "PASS",
            "readiness": "PASS",
            "generation": "PASS",
            "assertions": "PASS" if passed else "FAIL",
        },
        checks=checks,
        readiness={
            "provider_mode": readiness.provider_mode,
            "readiness_status": readiness.readiness_status,
            "model_profile": readiness.model_profile,
            "model_ref": readiness.model_ref,
            "deployment_id": readiness.deployment_id,
            "route_id": readiness.route_id,
            "source": readiness.source,
            "cache_status": readiness.cache_status,
        },
        generation={
            "mo_generation_id": result.mo_generation_id,
            "model_profile": result.model_profile,
            "model_ref": result.model_ref,
            "deployment_id": result.deployment_id,
            "route_id": result.route_id,
            "finish_reason": result.finish_reason,
            "provider_output_sha256": result.provider_output_sha256,
            "provider_output_size_bytes": result.provider_output_size_bytes,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
        },
        issues=[]
        if passed
        else [{"stage": "assertions", "error_code": "LIVE_ASSERTION_FAILED"}],
    )


def _failure(stage: str, error_code: str) -> dict[str, Any]:
    return _evidence(
        status="FAIL",
        stages={"activation": "PASS", stage: "FAIL"},
        checks={},
        readiness=None,
        generation=None,
        issues=[{"stage": stage, "error_code": error_code}],
    )


def _evidence(
    *,
    status: str,
    stages: dict[str, str],
    checks: dict[str, bool],
    readiness: dict[str, Any] | None,
    generation: dict[str, Any] | None,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "phase": "P6.5",
        "slice": "P6.5-S1",
        "status": status,
        "stages": stages,
        "checks": checks,
        "readiness": readiness,
        "generation": generation,
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "excluded": [
                "provider_url",
                "provider_endpoint",
                "api_key",
                "service_token",
                "raw_prompt",
                "raw_output",
                "hidden_reasoning",
            ],
        },
        "next_slice": "P6.5-S2" if status == "PASS" else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"p65_s1_ae_mo_generation_live_smoke=skipped reason={ACTIVATION_ENV}"
    generation = evidence.get("generation")
    model_ref = generation.get("model_ref") if isinstance(generation, dict) else None
    return (
        "p65_s1_ae_mo_generation_live_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"model_ref={model_ref or 'unavailable'} "
        f"checks={sum(bool(value) for value in evidence.get('checks', {}).values())} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def write_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    resolved = output_path.expanduser().resolve()
    if not resolved.is_relative_to(Path("/tmp").resolve()):
        raise ValueError("protected live evidence output must be below /tmp")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected P6.5-S1 AE-to-MO live generation smoke."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_p65_s1_ae_mo_generation_live_smoke()
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
