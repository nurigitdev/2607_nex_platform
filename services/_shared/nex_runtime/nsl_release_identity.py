from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .nsl_package_admission import NslPackageAdmissionError

NSL_RELEASE_IDENTITY_SCHEMA_VERSION = "nsl_release_identity.v1"
NSL_REPOSITORY = "nurigitdev/2608_nsl"
_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def build_nsl_release_identity(
    admission: Mapping[str, Any],
    *,
    repository: str,
    source_tree: str,
    expected_source_revision: str,
    expected_source_tree: str,
    expected_wheel_sha256: str,
    certification_reference: str,
) -> dict[str, Any]:
    """Bind a passing wheel admission to one immutable source release."""

    errors: list[str] = []
    if admission.get("status") != "PASS":
        errors.append("release identity requires a passing wheel admission")
    if repository != NSL_REPOSITORY:
        errors.append("unexpected NSL repository")

    source_revision = str(admission.get("source_revision", ""))
    if not _GIT_OBJECT_ID.fullmatch(source_revision):
        errors.append("invalid NSL source revision")
    if not _GIT_OBJECT_ID.fullmatch(source_tree):
        errors.append("invalid NSL source tree")
    if not _GIT_OBJECT_ID.fullmatch(expected_source_revision):
        errors.append("invalid expected NSL source revision")
    elif source_revision != expected_source_revision:
        errors.append("NSL source revision does not match release identity")
    if not _GIT_OBJECT_ID.fullmatch(expected_source_tree):
        errors.append("invalid expected NSL source tree")
    elif source_tree != expected_source_tree:
        errors.append("NSL source tree does not match release identity")

    wheel_sha256 = str(admission.get("wheel_sha256", ""))
    if not _HASH_REF.fullmatch(expected_wheel_sha256):
        errors.append("invalid expected NSL wheel digest")
    elif wheel_sha256 != expected_wheel_sha256:
        errors.append("NSL wheel digest does not match release identity")
    if admission.get("source_tree_clean") is not True:
        errors.append("NSL release identity requires a clean source tree")
    if (
        not isinstance(certification_reference, str)
        or not certification_reference.strip()
        or len(certification_reference) > 512
    ):
        errors.append("NSL certification reference is invalid")

    requirements = admission.get("requirements")
    symbols = admission.get("public_api_symbols")
    if not isinstance(requirements, list) or not all(
        isinstance(item, str) and item for item in requirements
    ):
        errors.append("NSL release dependency inventory is invalid")
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(item, str) or not item for item in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        errors.append("NSL release public API inventory is invalid")
    if errors:
        raise NslPackageAdmissionError("; ".join(errors))

    return {
        "schema_version": NSL_RELEASE_IDENTITY_SCHEMA_VERSION,
        "status": "PASS",
        "repository": repository,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "distribution": admission["distribution"],
        "package_version": admission["package_version"],
        "wheel_filename": admission["wheel_filename"],
        "wheel_sha256": wheel_sha256,
        "wheel_size": admission["wheel_size"],
        "requires_python": admission["requires_python"],
        "requirements": list(requirements),
        "public_api_symbols": list(symbols),
        "platform_lock_sha256": admission["platform_lock_sha256"],
        "certification_reference": certification_reference.strip(),
        "record_file_count": admission["record_file_count"],
        "record_integrity_count": admission["record_integrity_count"],
    }
