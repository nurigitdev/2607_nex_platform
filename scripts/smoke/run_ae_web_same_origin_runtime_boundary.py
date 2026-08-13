#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts" / "smoke"
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_web_credential_login_browser_harness_smoke import (  # noqa: E402
    safe_browser_config,
)
from run_ae_web_credential_login_browser_smoke_boundary import (  # noqa: E402
    assert_boundary_evidence_redacted,
    run_ae_web_credential_login_browser_smoke_boundary,
)


SCHEMA_VERSION = "ae_web_same_origin_runtime_boundary.v1"
PROXY_TARGET_ENV = "AE_API_PROXY_TARGET"
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
SERVE_SCRIPT = WEB_ROOT / "scripts" / "serve.mjs"
RUNTIME_CONFIG = WEB_ROOT / "src" / "runtimeConfig.js"
SESSION_CLIENT = WEB_ROOT / "src" / "sessionClient.js"
PACKAGE_JSON = WEB_ROOT / "package.json"
PROXY_TEST = WEB_ROOT / "test" / "serveProxy.test.mjs"

REQUIRED_SERVE_TOKENS = (
    "AE_API_PROXY_PREFIX",
    "\"/ae-api\"",
    "AE_API_PROXY_TARGET",
    "createAeWebServer",
    "isProxyPath",
    "proxyApiRequest",
    "proxyRequestHeaders",
    "apiProxyTarget && isProxyPath",
)

REQUIRED_RUNTIME_TOKENS = (
    "normalizeAeBaseUrl",
    "trimmed.startsWith(\"/\")",
    "parsed.username || parsed.password",
    "FETCH_MODE_NOT_ENABLED",
)

REQUIRED_SESSION_CLIENT_TOKENS = (
    "/api/v1/auth/session",
    "/api/v1/auth/session/login",
    "/api/v1/auth/session/logout",
    "credentials: \"same-origin\"",
    "ALLOWED_LOGIN_ROOT_SECRET_FIELDS",
)

REQUIRED_PACKAGE_TOKENS = ("\"dev\": \"node scripts/serve.mjs\"",)
PROTECTED_ENV_KEYS = (PROXY_TARGET_ENV,)


def run_ae_web_same_origin_runtime_boundary(
    environ: dict[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    browser_boundary = run_ae_web_credential_login_browser_smoke_boundary(
        {},
        browser_config=safe_browser_config(),
    )
    file_checks = _file_checks(root_dir)
    token_checks = {
        "serve": _token_checks(_read_text(root_dir / _relative(SERVE_SCRIPT)), REQUIRED_SERVE_TOKENS),
        "runtime_config": _token_checks(
            _read_text(root_dir / _relative(RUNTIME_CONFIG)),
            REQUIRED_RUNTIME_TOKENS,
        ),
        "session_client": _token_checks(
            _read_text(root_dir / _relative(SESSION_CLIENT)),
            REQUIRED_SESSION_CLIENT_TOKENS,
        ),
        "package": _token_checks(
            _read_text(root_dir / _relative(PACKAGE_JSON)),
            REQUIRED_PACKAGE_TOKENS,
        ),
    }
    issues = [
        *[
            _issue("file_missing", item["path"], "required file is missing")
            for item in file_checks
            if not item["present"]
        ],
        *[
            _issue("token_missing", f"{group}:{item['token']}", "required token is missing")
            for group, items in token_checks.items()
            for item in items
            if not item["present"]
        ],
    ]
    checks = {
        "files_present": all(item["present"] for item in file_checks),
        "dev_server_exports_proxy": all(item["present"] for item in token_checks["serve"]),
        "proxy_default_disabled": _source_defaults_proxy_disabled(
            _read_text(root_dir / _relative(SERVE_SCRIPT))
        ),
        "runtime_allows_same_origin_base_path": all(
            item["present"] for item in token_checks["runtime_config"]
        ),
        "session_client_uses_same_origin_credentials": all(
            item["present"] for item in token_checks["session_client"]
        ),
        "package_dev_script_wired": all(
            item["present"] for item in token_checks["package"]
        ),
        "browser_boundary_config_safe": browser_boundary["status"] != "FAIL",
        "browser_config_uses_ae_api_base_path": (
            safe_browser_config().get("ae_base_url") == "/ae-api"
        ),
        "redacted_evidence": True,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    evidence = {
        "boundary_schema_version": SCHEMA_VERSION,
        "status": status,
        "proxy": {
            "prefix": "/ae-api",
            "target_env": PROXY_TARGET_ENV,
            "default_enabled": False,
            "same_origin_browser_path": "/ae-api/api/v1/auth/session/login",
            "target_configured": bool(env.get(PROXY_TARGET_ENV)),
            "target_value": "configured" if env.get(PROXY_TARGET_ENV) else "missing",
        },
        "browser_boundary": {
            "schema_version": browser_boundary["evidence_schema_version"],
            "status": browser_boundary["status"],
            "safe_browser_config": True,
        },
        "files": file_checks,
        "tokens": token_checks,
        "checks": checks,
        "issues": issues,
        "redaction": {
            "proxy_target_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "password_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
        },
    }
    assert_same_origin_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _file_checks(root_dir: Path) -> list[dict[str, object]]:
    paths = (
        SERVE_SCRIPT,
        RUNTIME_CONFIG,
        SESSION_CLIENT,
        PACKAGE_JSON,
        PROXY_TEST,
    )
    return [
        {
            "path": _relative_label(path, root_dir),
            "present": (root_dir / _relative(path)).exists(),
        }
        for path in paths
    ]


def _token_checks(text: str, tokens: tuple[str, ...]) -> list[dict[str, object]]:
    return [{"token": token, "present": token in text} for token in tokens]


def _source_defaults_proxy_disabled(serve_source: str) -> bool:
    return 'process.env.AE_API_PROXY_TARGET || ""' in serve_source


def assert_same_origin_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    assert_boundary_evidence_redacted(serialized_evidence, {})
    for key in PROTECTED_ENV_KEYS:
        value = environ.get(key)
        if value and len(value) >= 8 and value in serialized_evidence:
            raise ValueError(
                "AE Web same-origin runtime boundary evidence contains "
                f"unredacted environment value: {key}"
            )


def write_boundary_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_same_origin_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def _issue(category: str, subject: str, detail: str) -> dict[str, str]:
    return {"category": category, "subject": subject, "detail": detail}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _relative(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return Path(path.name)


def _relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        file_count = sum(1 for item in evidence["files"] if item["present"])
        return (
            "ae_web_same_origin_runtime_boundary=pass "
            f"proxy={evidence['proxy']['prefix']} "
            f"files={file_count}/{len(evidence['files'])} "
            f"browser_config=safe"
        )
    return (
        "ae_web_same_origin_runtime_boundary=fail "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate AE Web same-origin runtime/proxy boundary."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_same_origin_runtime_boundary()
        if args.output:
            write_boundary_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except ValueError as exc:
        print(
            "ae_web_same_origin_runtime_boundary=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
