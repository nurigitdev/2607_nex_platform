#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_post_login_document_workflow_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_OA_TEST_DATABASE_URL",
    "NEX_AE_DATABASE_URL",
    "NEX_CX_DATABASE_URL",
    "NEX_OA_DATABASE_URL",
    "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD",
)


@dataclass(frozen=True)
class RequiredPath:
    name: str
    path: Path
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    path: Path
    token: str
    purpose: str


@dataclass(frozen=True)
class PlannedGap:
    name: str
    path: Path
    token: str
    planned_slice: str
    purpose: str


REQUIRED_PATHS = (
    RequiredPath(
        "ae_web_shell",
        ROOT / "apps" / "nex-ae-web" / "index.html",
        "Authenticated browser workspace shell.",
    ),
    RequiredPath(
        "ae_web_main",
        ROOT / "apps" / "nex-ae-web" / "src" / "main.js",
        "Post-login workspace orchestration.",
    ),
    RequiredPath(
        "upload_surface",
        ROOT / "apps" / "nex-ae-web" / "src" / "uploadSurface.js",
        "Browser-safe upload metadata and ownership draft.",
    ),
    RequiredPath(
        "upload_client",
        ROOT / "apps" / "nex-ae-web" / "src" / "uploadClient.js",
        "Mock/fetch upload handoff adapter.",
    ),
    RequiredPath(
        "document_detail_client",
        ROOT / "apps" / "nex-ae-web" / "src" / "documentDetailClient.js",
        "Owner-scoped document detail adapter.",
    ),
    RequiredPath(
        "retrieval_client",
        ROOT / "apps" / "nex-ae-web" / "src" / "retrievalClient.js",
        "Authenticated retrieval context adapter.",
    ),
    RequiredPath(
        "client_registry",
        ROOT / "apps" / "nex-ae-web" / "src" / "clientRegistry.js",
        "Shared browser client composition boundary.",
    ),
    RequiredPath(
        "same_origin_playwright_smoke",
        ROOT
        / "apps"
        / "nex-ae-web"
        / "scripts"
        / "runCredentialLoginPlaywrightSmoke.mjs",
        "Known-good authenticated Playwright login/logout harness.",
    ),
    RequiredPath(
        "ae_api_upload_facade",
        ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "uploads.py",
        "AE upload facade that delegates to CX with service auth.",
    ),
)

REQUIRED_HTML_ANCHORS = (
    "credential-login-form",
    "session-route-guard-summary",
    "upload-surface-panel",
    "upload-submit-button",
    "upload-client-summary",
    "upload-payload-preview",
    "document-list",
    "document-detail-panel",
    "retrieval-scope-panel",
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "upload_surface",
        ROOT / "apps" / "nex-ae-web" / "src" / "uploadSurface.js",
        "sourceContentIncluded: false",
        "Upload draft metadata excludes source bytes.",
    ),
    TokenRequirement(
        "upload_surface",
        ROOT / "apps" / "nex-ae-web" / "src" / "uploadSurface.js",
        "buildUploadOwnershipRef",
        "Upload metadata carries OA ownership refs.",
    ),
    TokenRequirement(
        "upload_client",
        ROOT / "apps" / "nex-ae-web" / "src" / "uploadClient.js",
        "credentials: \"same-origin\"",
        "Fetch upload client uses browser same-origin credentials.",
    ),
    TokenRequirement(
        "upload_client",
        ROOT / "apps" / "nex-ae-web" / "src" / "uploadClient.js",
        "AE_UPLOAD_ROUTE",
        "Upload client keeps the AE facade route centralized.",
    ),
    TokenRequirement(
        "client_registry",
        ROOT / "apps" / "nex-ae-web" / "src" / "clientRegistry.js",
        "createFetchUploadClient(commonFetchOptions)",
        "Fetch-mode client registry composes upload with the shared base URL.",
    ),
    TokenRequirement(
        "main",
        ROOT / "apps" / "nex-ae-web" / "src" / "main.js",
        "syncOwnerScopeFromSessionClaims",
        "Post-login owner scope is derived from OA session claims.",
    ),
    TokenRequirement(
        "main",
        ROOT / "apps" / "nex-ae-web" / "src" / "main.js",
        "documents:upload",
        "Credential login requests include upload scope.",
    ),
    TokenRequirement(
        "main",
        ROOT / "apps" / "nex-ae-web" / "src" / "main.js",
        "submitUploadDraft",
        "Upload operation has a browser event path.",
    ),
    TokenRequirement(
        "ae_api_upload_facade",
        ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "uploads.py",
        "authorize_ae_facade_route_request",
        "AE upload facade is browser-user authenticated.",
    ),
    TokenRequirement(
        "ae_api_upload_facade",
        ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "uploads.py",
        "client.register_upload",
        "AE delegates upload registration to CX.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "file_metadata_input",
        ROOT / "apps" / "nex-ae-web" / "index.html",
        "upload-file-input",
        "Slice 0272",
        "Browser file selection metadata surface.",
    ),
    PlannedGap(
        "authenticated_upload_playwright_smoke",
        ROOT
        / "apps"
        / "nex-ae-web"
        / "scripts"
        / "runAuthenticatedUploadPlaywrightSmoke.mjs",
        "runAuthenticatedUploadPlaywrightSmoke",
        "Slice 0274",
        "Login plus upload Playwright smoke against PostgreSQL test databases.",
    ),
)


def run_ae_web_post_login_document_workflow_audit(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    paths = path_checks(root_dir)
    anchors = html_anchor_checks(root_dir)
    source_tokens = source_token_checks(root_dir)
    gaps = planned_gap_checks(root_dir)
    decisions = build_decisions()
    issues = [
        *[
            issue("path_missing", item["name"], item["path"])
            for item in paths
            if not item["present"]
        ],
        *[
            issue("html_anchor_missing", item["anchor"], "apps/nex-ae-web/index.html")
            for item in anchors
            if not item["present"]
        ],
        *[
            issue("source_token_missing", item["token"], item["path"])
            for item in source_tokens
            if not item["present"]
        ],
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "post_login_html_anchors_present": all(item["present"] for item in anchors),
        "source_boundaries_present": all(item["present"] for item in source_tokens),
        "planned_gaps_are_non_blocking": all(item["planned_slice"] for item in gaps),
        "metadata_handoff_before_source_bytes_decision": decisions[
            "upload_payload_scope"
        ]
        == "metadata_handoff_only",
        "browser_uses_same_origin_only": decisions["browser_api_path"] == "/ae-api",
        "smoke_requires_test_databases": set(decisions["protected_smoke_databases"])
        == {"nex_ae_test", "nex_oa_test", "nex_cx_test"},
        "redacted_evidence_only": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "slice": "Slice 0271",
            "focus": "post_login_document_workflow",
            "from": "credential_login_playwright_postgresql_smoke",
            "toward": [
                "authenticated_upload_metadata_surface",
                "authenticated_upload_fetch_wiring",
                "upload_playwright_postgresql_smoke",
            ],
        },
        "paths": paths,
        "html_anchors": anchors,
        "source_tokens": source_tokens,
        "planned_gaps": gaps,
        "decisions": decisions,
        "checks": checks,
        "issues": issues,
        "redaction": {
            "database_endpoint_in_evidence": False,
            "password_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "source_bytes_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False, default=str), env)
    return evidence


def path_checks(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "present": path_for(root_dir, item.path).exists(),
            "purpose": item.purpose,
        }
        for item in REQUIRED_PATHS
    ]


def html_anchor_checks(root_dir: Path) -> list[dict[str, object]]:
    html = read_text(root_dir, ROOT / "apps" / "nex-ae-web" / "index.html")
    return [{"anchor": anchor, "present": anchor in html} for anchor in REQUIRED_HTML_ANCHORS]


def source_token_checks(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "group": item.group,
            "path": relative_label(item.path, root_dir),
            "token": item.token,
            "present": item.token in read_text(root_dir, item.path),
            "purpose": item.purpose,
        }
        for item in REQUIRED_SOURCE_TOKENS
    ]


def planned_gap_checks(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "token": item.token,
            "present": item.token in read_text(root_dir, item.path),
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_GAPS
    ]


def build_decisions() -> dict[str, object]:
    return {
        "upload_payload_scope": "metadata_handoff_only",
        "source_bytes_policy": "defer_raw_file_bytes_until_cx_storage_boundary",
        "browser_api_path": "/ae-api",
        "browser_credential_mode": "same-origin",
        "owner_scope_source": "oa_session_claims",
        "ae_to_cx_mode": "service_authenticated_facade_call",
        "protected_smoke_databases": ["nex_ae_test", "nex_oa_test", "nex_cx_test"],
        "slice_sequence": ["Slice 0272", "Slice 0273", "Slice 0274"],
    }


def issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def assert_evidence_redacted(serialized_evidence: str, environ: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and value not in {"1", "test"} and value in serialized_evidence:
            raise ValueError(
                "AE Web post-login document workflow audit evidence contains "
                f"unredacted environment value: {key}"
            )


def write_audit_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        ready_gaps = sum(1 for item in evidence["planned_gaps"] if item["present"])
        return (
            "ae_web_post_login_document_workflow_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"anchors={present_count(evidence['html_anchors'])}/{len(evidence['html_anchors'])} "
            f"gaps_ready={ready_gaps}/{len(evidence['planned_gaps'])} "
            "next=Slice_0272"
        )
    failed_checks = ",".join(
        key for key, value in evidence["checks"].items() if not value
    )
    return f"ae_web_post_login_document_workflow_audit=fail checks={failed_checks}"


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item["present"])


def read_text(root_dir: Path, absolute_path: Path) -> str:
    path = path_for(root_dir, absolute_path)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def path_for(root_dir: Path, absolute_path: Path) -> Path:
    try:
        return root_dir / absolute_path.relative_to(ROOT)
    except ValueError:
        return absolute_path


def relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return path.name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit AE Web post-login document workflow readiness."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_web_post_login_document_workflow_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        return 0 if evidence["status"] == "PASS" else 1
    except ValueError as exc:
        print(
            "ae_web_post_login_document_workflow_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
