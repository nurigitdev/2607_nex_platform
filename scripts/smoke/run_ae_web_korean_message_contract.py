#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_korean_message_contract.v1"
CATALOG_PATH = "apps/nex-ae-web/src/locales/messages.js"
INDEX_PATH = "apps/nex-ae-web/index.html"
MAIN_PATH = "apps/nex-ae-web/src/main.js"

REQUIRED_KEYS = (
    "app.title",
    "nav.workspace",
    "summary.workspace",
    "chat.prompt",
    "action.send",
    "auth.login",
    "upload.title",
    "retrieval.title",
    "artifact.title",
    "status.ready",
    "status.running",
    "status.failed",
    "status.validated",
)


def run_ae_web_korean_message_contract(root: Path = ROOT) -> dict[str, Any]:
    catalog = _read_text(root / CATALOG_PATH)
    index = _read_text(root / INDEX_PATH)
    main = _read_text(root / MAIN_PATH)
    key_occurrences = {
        key: catalog.count(f'"{key}"') for key in REQUIRED_KEYS
    }
    static_binding_count = index.count("data-i18n=")
    accessible_binding_count = index.count("data-i18n-aria-label=")
    checks = {
        "catalog_present": bool(catalog),
        "korean_default_frozen": (
            'DEFAULT_LOCALE = "ko"' in catalog and '<html lang="ko">' in index
        ),
        "korean_english_catalogs_present": all(
            token in catalog for token in ("const ko", "const en", '"ko", "en"')
        ),
        "required_key_parity_present": all(
            count == 2 for count in key_occurrences.values()
        ),
        "catalog_parity_guard_present": "validateCatalogParity" in catalog,
        "static_message_bindings_present": static_binding_count >= 35,
        "accessible_message_bindings_present": accessible_binding_count >= 5,
        "composition_applies_catalog": all(
            token in main
            for token in (
                'from "./locales/messages.js"',
                "applyDocumentMessages(document, activeLocale)",
                "return statusMessage(status, activeLocale)",
                'uiMessage("timeline.event_count"',
            )
        ),
        "node_contract_test_present": (
            root / "apps/nex-ae-web/test/uiMessages.test.mjs"
        ).is_file(),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1383",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "message_contract_readiness": "KOREAN_DEFAULT_READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "required_key_occurrences": key_occurrences,
        "summary": {
            "locale_count": 2,
            "required_key_count": len(REQUIRED_KEYS),
            "parity_key_count": sum(
                count == 2 for count in key_occurrences.values()
            ),
            "static_binding_count": static_binding_count,
            "accessible_binding_count": accessible_binding_count,
            "issue_count": len(issues),
        },
        "decision": {
            "default_locale": "ko",
            "fallback_locale": "ko",
            "english_ready": passed,
            "new_table_required": False,
            "remote_provider_required": False,
            "next_slice": "1384" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_web_korean_message_contract=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_korean_message_contract=pass "
        f"locales={summary.get('locale_count', 0)} "
        f"keys={summary.get('parity_key_count', 0)}/"
        f"{summary.get('required_key_count', 0)} "
        f"bindings={summary.get('static_binding_count', 0)} "
        f"aria={summary.get('accessible_binding_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_korean_message_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
