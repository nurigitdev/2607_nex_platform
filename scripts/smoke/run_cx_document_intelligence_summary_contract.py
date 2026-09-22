#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from nex_cx.document_intelligence import (  # noqa: E402
    DocumentIntelligenceContractError,
    build_summary_generation_profile,
    build_summary_manifest,
    build_summary_source_snapshot,
    evaluate_summary_freshness,
    public_summary_manifest,
)


SCHEMA_VERSION = "cx_document_intelligence_summary_contract_evidence.v1"


def run_cx_document_intelligence_summary_contract() -> dict[str, Any]:
    source = _source("a")
    profile = _profile("v1")
    manifest = build_summary_manifest(
        source=source,
        profile=profile,
        summary_text_sha256=_hex("summary"),
        summary_char_count=420,
        summary_storage_key="20260922/aa/summary.md",
    )
    repeated = build_summary_manifest(
        source=source,
        profile=profile,
        summary_text_sha256=_hex("summary"),
        summary_char_count=420,
        summary_storage_key="20260922/aa/summary.md",
    )
    fresh = evaluate_summary_freshness(
        manifest,
        current_source=source,
        current_profile=profile,
    )
    changed_source = evaluate_summary_freshness(
        manifest,
        current_source=_source("b"),
        current_profile=profile,
    )
    changed_profile = evaluate_summary_freshness(
        manifest,
        current_source=source,
        current_profile=_profile("v2"),
    )
    public = public_summary_manifest(manifest)
    invalid_rejected = False
    try:
        build_summary_manifest(
            source=source,
            profile=profile,
            summary_text_sha256=_hex("oversized"),
            summary_char_count=1001,
            summary_storage_key="summary.md",
        )
    except DocumentIntelligenceContractError:
        invalid_rejected = True
    serialized = json.dumps(public, sort_keys=True)
    checks = {
        "deterministic_identity": (
            manifest["document_summary_id"] == repeated["document_summary_id"]
        ),
        "summary_hard_limit_enforced": invalid_rejected,
        "ready_manifest_is_fresh": (
            fresh["state"] == "READY" and fresh["usable"] is True
        ),
        "source_change_is_stale": changed_source["reasons"] == ["SOURCE_CHANGED"],
        "profile_change_is_stale": (
            changed_profile["reasons"] == ["GENERATION_PROFILE_CHANGED"]
        ),
        "source_hash_bound": (
            manifest["source"]["source_markdown_sha256"] == _hex("source-a")
        ),
        "profile_hash_bound": (
            manifest["generation_profile"]["model_revision"] == "v1"
        ),
        "private_text_absent": "private summary text" not in serialized,
        "private_storage_key_absent": "summary_storage_key" not in serialized,
        "deployment_id_absent": "deployment_id" not in serialized,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0952",
        "requirement": "S96",
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed,
        "summary_hard_limit_chars": 1000,
        "generation_model": profile["model_profile_id"],
        "embedding_model": "Qwen3-Embedding-4B",
        "postgres_required": False,
        "remote_provider_required": False,
        "next_slice": "0953",
    }


def _source(label: str) -> dict[str, Any]:
    return build_summary_source_snapshot(
        document_id="document-contract",
        content_object_id="content-contract",
        extraction_artifact_id=f"extraction-{label}",
        source_markdown_sha256=_hex(f"source-{label}"),
    )


def _profile(revision: str) -> dict[str, Any]:
    return build_summary_generation_profile(
        provider_alias="general-llm-default",
        model_profile_id="Qwen3.5-122B-A10B-NVFP4",
        model_revision=revision,
        deployment_id="contract-local",
        prompt_template_version_id="prompt-v1",
    )


def _hex(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "cx_document_intelligence_summary_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={result.get('passed_checks', 0)}/"
        f"{len(result.get('checks') or {})} "
        f"hard_limit={result.get('summary_hard_limit_chars', 0)} "
        f"postgres_required={result.get('postgres_required', True)} "
        f"remote_required={result.get('remote_provider_required', True)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_document_intelligence_summary_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
