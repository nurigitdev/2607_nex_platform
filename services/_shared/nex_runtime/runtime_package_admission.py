from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RUNTIME_CHECK_MODE_ENV = "NEX_RUNTIME_CHECK_MODE"
RUNTIME_PACKAGE_CHECK_MODE = "PACKAGE"


class RuntimePackageAdmissionError(ValueError):
    pass


def runtime_package_check_requested(environ: Mapping[str, str]) -> bool:
    return (
        str(environ.get(RUNTIME_CHECK_MODE_ENV) or "").strip().upper()
        == RUNTIME_PACKAGE_CHECK_MODE
    )


def build_runtime_package_check(source_check: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(source_check)
    if record.get("status") != "PASS" or not record.get("process_id"):
        raise RuntimePackageAdmissionError("runtime source package check is invalid")
    return {
        **record,
        "check_scope": RUNTIME_PACKAGE_CHECK_MODE,
        "package_ready": True,
        "runtime_ready": False,
        "database": {"status": "NOT_REQUESTED"},
        "secret_included": False,
    }
