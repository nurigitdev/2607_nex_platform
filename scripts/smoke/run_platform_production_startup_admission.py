#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_configuration import (  # noqa: E402
    load_production_configuration_manifest,
)
from nex_runtime.production_startup_admission import (  # noqa: E402
    ProductionStartupAdmissionError,
    admit_production_startup,
    production_startup_admission_projection,
)
from nex_runtime.runtime_profiles import (  # noqa: E402
    runtime_profile_environment_overlay,
)


SCHEMA_VERSION = "platform_production_startup_admission_evidence.v1"
_PUBLIC_ENDPOINTS = {
    "NEX_OA_BASE_URL": "https://oa.platform.example",
    "NEX_AG_BASE_URL": "https://ag.platform.example",
    "NEX_AE_API_BASE_URL": "https://ae-api.platform.example",
    "NEX_CX_BASE_URL": "https://cx.platform.example",
    "NEX_MO_BASE_URL": "https://mo.platform.example",
    "NEX_AE_WEB_BASE_URL": "https://ae.platform.example",
    "NEX_MO_REMOTE_EMBEDDING_URL": (
        "https://embedding.models.example/v1/embeddings"
    ),
    "NEX_MO_REMOTE_RERANKER_URL": "https://reranker.models.example/v1/rerank",
    "NEX_MO_VLLM_BASE_URL": "https://generation.models.example/v1",
}
_CONTROL_VALUES = {
    "NEX_CONFIG_GENERATION": "config:2026-10-07.1",
    "NEX_SECRET_GENERATION": "secret:2026-10-07.1",
    "NEX_TLS_GENERATION": "tls:2026-10-07.1",
    "NEX_TLS_TERMINATION_POLICY_REF": "tls://managed/platform/policy@v1",
    "NEX_TLS_CERTIFICATE_REF": "tls://managed/platform/certificate@v1",
    "NEX_TLS_TRUST_BUNDLE_REF": "tls://managed/platform/trust-bundle@v1",
}


def run_platform_production_startup_admission(
    root: Path = ROOT,
) -> dict[str, Any]:
    environment = _synthetic_environment(root)
    admission = admit_production_startup(environment, root=root)
    projection = production_startup_admission_projection(admission)
    fail_closed_cases = {}
    for case_id, mutation in (
        (
            "missing_secret_reference",
            lambda value: value.pop("NEX_OA_DATABASE_URL_REF"),
        ),
        (
            "raw_secret_input",
            lambda value: value.__setitem__(
                "NEX_OA_DATABASE_URL", "must-not-be-admitted"
            ),
        ),
        (
            "insecure_endpoint",
            lambda value: value.__setitem__(
                "NEX_OA_BASE_URL", "http://oa.platform.example"
            ),
        ),
        (
            "missing_tls_reference",
            lambda value: value.pop("NEX_TLS_CERTIFICATE_REF"),
        ),
        (
            "mixed_generation",
            lambda value: value.__setitem__("NEX_SECRET_GENERATION", "changeme"),
        ),
        (
            "profile_conflict",
            lambda value: value.__setitem__("NEX_PROFILE", "staging_live"),
        ),
    ):
        candidate = dict(environment)
        mutation(candidate)
        try:
            admit_production_startup(candidate, root=root)
        except ProductionStartupAdmissionError:
            fail_closed_cases[case_id] = True
        else:
            fail_closed_cases[case_id] = False
    passed = all(fail_closed_cases.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1425",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "admission": projection,
        "fail_closed_cases": fail_closed_cases,
        "summary": {
            "secret_reference_count": projection["secret_reference_count"],
            "public_connection_count": projection["public_connection_count"],
            "control_environment_count": projection["control_environment_count"],
            "https_endpoint_count": projection["https_endpoint_count"],
            "fail_closed_case_count": len(fail_closed_cases),
        },
        "decision": {
            "admitted_for_secret_materialization": passed,
            "secret_materialization_performed": False,
            "external_connection_required": False,
            "production_deployment_approved": False,
            "next_slice": "1426" if passed else "blocked",
        },
    }


def _synthetic_environment(root: Path = ROOT) -> dict[str, str]:
    manifest = load_production_configuration_manifest(root)
    environment = runtime_profile_environment_overlay("production")
    for binding in manifest.bindings:
        if binding.input_kind == "external_secret_reference":
            resource = binding.target_environment_name.lower().replace("_", "-")
            environment[binding.source_environment_name] = (
                f"secret://external/nex-platform/{resource}@v1"
            )
        else:
            environment[binding.source_environment_name] = _PUBLIC_ENDPOINTS[
                binding.source_environment_name
            ]
    environment.update(_CONTROL_VALUES)
    return environment


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_production_startup_admission=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_startup_admission=pass "
        f"secrets={summary.get('secret_reference_count', 0)} "
        f"connections={summary.get('public_connection_count', 0)} "
        f"controls={summary.get('control_environment_count', 0)} "
        f"https={summary.get('https_endpoint_count', 0)} "
        f"fail_closed={summary.get('fail_closed_case_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_production_startup_admission()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

