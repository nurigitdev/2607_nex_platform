from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

MYBEE_PRODUCT_ADMISSION_SCHEMA_VERSION = "ae.mybee_product_admission.v1"
EXPECTED_DOMAIN_ID = "mybee"
EXPECTED_PACKAGE_VERSION = "0.1.0"
EXPECTED_PLATFORM_OWNERS = frozenset(
    {
        "nex-oa",
        "nex-ae-api",
        "nex-wc",
        "nex-eos",
        "nex-wa",
        "nex-cx",
        "nex-mo",
        "nex-ag",
    }
)
REQUIRED_CONSUMER_EXPORTS = (
    "HttpVoucherCandidateProviderTransport",
    "NexVoucherCandidateClient",
)


class MyBeeProductAdmissionError(RuntimeError):
    pass


def inspect_mybee_product_package() -> dict[str, Any]:
    issues: list[str] = []
    try:
        package = importlib.import_module("mybee_ax")
        integrations = importlib.import_module("mybee_ax.integrations")
    except (ImportError, ModuleNotFoundError) as exc:
        return _projection(
            status="FAIL",
            domain_id=None,
            package_version=None,
            platform_owners=(),
            consumer_exports=(),
            issues=(f"MYBEE_PACKAGE_UNAVAILABLE:{exc.__class__.__name__}",),
        )

    domain_id = getattr(package, "DOMAIN_ID", None)
    package_version = getattr(package, "PACKAGE_VERSION", None)
    owners_value = getattr(package, "CANONICAL_PLATFORM_OWNERS", ())
    platform_owners = (
        tuple(str(item) for item in owners_value)
        if isinstance(owners_value, (tuple, list))
        else ()
    )
    consumer_exports = tuple(
        name for name in REQUIRED_CONSUMER_EXPORTS if hasattr(integrations, name)
    )
    if domain_id != EXPECTED_DOMAIN_ID:
        issues.append("MYBEE_DOMAIN_ID_MISMATCH")
    if package_version != EXPECTED_PACKAGE_VERSION:
        issues.append("MYBEE_PACKAGE_VERSION_MISMATCH")
    if set(platform_owners) != EXPECTED_PLATFORM_OWNERS:
        issues.append("MYBEE_PLATFORM_OWNER_SET_MISMATCH")
    if consumer_exports != REQUIRED_CONSUMER_EXPORTS:
        issues.append("MYBEE_VOUCHER_CONSUMER_EXPORT_MISSING")
    return _projection(
        status="PASS" if not issues else "FAIL",
        domain_id=domain_id,
        package_version=package_version,
        platform_owners=platform_owners,
        consumer_exports=consumer_exports,
        issues=tuple(issues),
    )


def require_mybee_product_package() -> dict[str, Any]:
    admission = inspect_mybee_product_package()
    if admission["status"] != "PASS":
        raise MyBeeProductAdmissionError(
            "MyBee product package admission failed: "
            + ",".join(str(item) for item in admission["issues"])
        )
    return admission


def not_required_mybee_product_admission() -> dict[str, Any]:
    return {
        "schema_version": MYBEE_PRODUCT_ADMISSION_SCHEMA_VERSION,
        "status": "NOT_REQUIRED",
        "domain_id": EXPECTED_DOMAIN_ID,
        "package_version": EXPECTED_PACKAGE_VERSION,
        "platform_owners": [],
        "consumer_exports": [],
        "issues": [],
        "content_included": False,
        "secret_included": False,
    }


def _projection(
    *,
    status: str,
    domain_id: object,
    package_version: object,
    platform_owners: tuple[str, ...],
    consumer_exports: tuple[str, ...],
    issues: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": MYBEE_PRODUCT_ADMISSION_SCHEMA_VERSION,
        "status": status,
        "domain_id": domain_id,
        "package_version": package_version,
        "platform_owners": sorted(platform_owners),
        "consumer_exports": list(consumer_exports),
        "issues": list(issues),
        "content_included": False,
        "secret_included": False,
    }


def mybee_product_admission_ready(value: Mapping[str, Any]) -> bool:
    return value.get("status") in {"PASS", "NOT_REQUIRED"}
