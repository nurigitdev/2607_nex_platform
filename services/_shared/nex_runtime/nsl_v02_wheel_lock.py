from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from .nsl_package_admission import (
    NSL_DISTRIBUTION,
    NSL_WHEEL_ADMISSION_SCHEMA_VERSION,
    NslPackageAdmissionError,
)
from .nsl_release_identity import (
    NSL_RELEASE_IDENTITY_SCHEMA_VERSION,
    NSL_REPOSITORY,
)

NSL_V02_WHEEL_LOCK_SCHEMA_VERSION = "nsl_wheel_lock.v2"
NSL_V02_ADMITTED_PACKAGE_VERSIONS = frozenset({"0.2.0", "0.2.1"})
_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCK_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "source_revision",
        "source_tree",
        "distribution",
        "package_version",
        "wheel_filename",
        "wheel_sha256",
        "wheel_size",
        "requires_python",
        "requirements",
        "platform_cryptography_requirement",
        "locked_cryptography_version",
        "platform_lock_sha256",
        "public_api_symbols",
        "certification_reference",
        "record_file_count",
        "record_integrity_count",
    }
)


def nsl_v02_wheel_lock_projection(
    release_identity: Mapping[str, Any], admission: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        release_identity.get("schema_version")
        != NSL_RELEASE_IDENTITY_SCHEMA_VERSION
        or release_identity.get("status") != "PASS"
    ):
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock requires a passing release identity"
        )
    if (
        admission.get("schema_version") != NSL_WHEEL_ADMISSION_SCHEMA_VERSION
        or admission.get("status") != "PASS"
    ):
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock requires a passing wheel admission"
        )
    try:
        lock = {
            "schema_version": NSL_V02_WHEEL_LOCK_SCHEMA_VERSION,
            "repository": release_identity["repository"],
            "source_revision": release_identity["source_revision"],
            "source_tree": release_identity["source_tree"],
            "distribution": release_identity["distribution"],
            "package_version": release_identity["package_version"],
            "wheel_filename": release_identity["wheel_filename"],
            "wheel_sha256": release_identity["wheel_sha256"],
            "wheel_size": release_identity["wheel_size"],
            "requires_python": release_identity["requires_python"],
            "requirements": list(release_identity["requirements"]),
            "platform_cryptography_requirement": admission[
                "platform_cryptography_requirement"
            ],
            "locked_cryptography_version": admission[
                "locked_cryptography_version"
            ],
            "platform_lock_sha256": release_identity["platform_lock_sha256"],
            "public_api_symbols": list(release_identity["public_api_symbols"]),
            "certification_reference": release_identity[
                "certification_reference"
            ],
            "record_file_count": release_identity["record_file_count"],
            "record_integrity_count": release_identity[
                "record_integrity_count"
            ],
        }
    except (KeyError, TypeError) as exc:
        raise NslPackageAdmissionError(
            "NSL v0.2 release identity is incomplete"
        ) from exc

    for field in (
        "source_revision",
        "distribution",
        "package_version",
        "wheel_filename",
        "wheel_sha256",
        "wheel_size",
        "requires_python",
        "requirements",
        "platform_lock_sha256",
        "public_api_symbols",
        "record_file_count",
        "record_integrity_count",
    ):
        if release_identity.get(field) != admission.get(field):
            raise NslPackageAdmissionError(
                f"NSL v0.2 identity and admission disagree on {field}"
            )
    return normalize_nsl_v02_wheel_lock(lock)


def validate_nsl_v02_wheel_lock(
    release_identity: Mapping[str, Any],
    admission: Mapping[str, Any],
    lock: Mapping[str, Any],
) -> None:
    normalized = normalize_nsl_v02_wheel_lock(lock)
    expected = nsl_v02_wheel_lock_projection(release_identity, admission)
    if normalized != expected:
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock does not match release identity"
        )


def normalize_nsl_v02_wheel_lock(lock: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(lock, Mapping) or set(lock) != _LOCK_FIELDS:
        raise NslPackageAdmissionError("NSL v0.2 wheel lock fields are invalid")
    normalized = dict(lock)
    if normalized["schema_version"] != NSL_V02_WHEEL_LOCK_SCHEMA_VERSION:
        raise NslPackageAdmissionError("NSL v0.2 wheel lock schema is invalid")
    if normalized["repository"] != NSL_REPOSITORY:
        raise NslPackageAdmissionError("NSL v0.2 wheel lock repository is invalid")
    if canonicalize_name(str(normalized["distribution"])) != NSL_DISTRIBUTION:
        raise NslPackageAdmissionError("NSL v0.2 wheel lock distribution is invalid")
    if normalized["package_version"] not in NSL_V02_ADMITTED_PACKAGE_VERSIONS:
        raise NslPackageAdmissionError("NSL v0.2 wheel lock version is invalid")
    for field in ("source_revision", "source_tree"):
        if not _GIT_OBJECT_ID.fullmatch(str(normalized[field])):
            raise NslPackageAdmissionError(
                f"NSL v0.2 wheel lock {field} is invalid"
            )
    for field in ("wheel_sha256", "platform_lock_sha256"):
        if not _HASH_REF.fullmatch(str(normalized[field])):
            raise NslPackageAdmissionError(
                f"NSL v0.2 wheel lock {field} is invalid"
            )

    wheel_filename = normalized["wheel_filename"]
    try:
        wheel_name, wheel_version, _, _ = parse_wheel_filename(str(wheel_filename))
    except (ValueError, InvalidVersion) as exc:
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock filename is invalid"
        ) from exc
    if (
        not isinstance(wheel_filename, str)
        or Path(wheel_filename).name != wheel_filename
        or canonicalize_name(wheel_name) != NSL_DISTRIBUTION
        or str(wheel_version) != normalized["package_version"]
    ):
        raise NslPackageAdmissionError("NSL v0.2 wheel lock filename is invalid")
    if normalized["requires_python"] != ">=3.12":
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock Python requirement is invalid"
        )

    requirements = _requirements(normalized["requirements"], "NSL")
    platform_requirements = _requirements(
        [normalized["platform_cryptography_requirement"]], "Platform"
    )
    cryptography_requirements = tuple(
        item
        for item in requirements
        if canonicalize_name(item.name) == "cryptography"
    )
    if len(cryptography_requirements) != 1:
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock requires one cryptography dependency"
        )
    platform_requirement = platform_requirements[0]
    if canonicalize_name(platform_requirement.name) != "cryptography":
        raise NslPackageAdmissionError(
            "NSL v0.2 Platform dependency must be cryptography"
        )
    try:
        locked_version = Version(str(normalized["locked_cryptography_version"]))
    except InvalidVersion as exc:
        raise NslPackageAdmissionError(
            "NSL v0.2 locked cryptography version is invalid"
        ) from exc
    if (
        locked_version not in cryptography_requirements[0].specifier
        or locked_version not in platform_requirement.specifier
    ):
        raise NslPackageAdmissionError(
            "NSL v0.2 locked cryptography version is incompatible"
        )

    symbols = normalized["public_api_symbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(item, str) or not item for item in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock public API symbols are invalid"
        )
    for field in ("wheel_size", "record_file_count", "record_integrity_count"):
        if type(normalized[field]) is not int or normalized[field] <= 0:
            raise NslPackageAdmissionError(
                f"NSL v0.2 wheel lock {field} is invalid"
            )
    if normalized["record_integrity_count"] != normalized["record_file_count"] - 1:
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock RECORD counts are inconsistent"
        )
    expected_certification = (
        f"nsl-linux-quality:{normalized['source_revision']}"
    )
    if normalized["certification_reference"] != expected_certification:
        raise NslPackageAdmissionError(
            "NSL v0.2 wheel lock certification is invalid"
        )
    return normalized


def _requirements(value: Any, owner: str) -> tuple[Requirement, ...]:
    if not isinstance(value, list) or not value:
        raise NslPackageAdmissionError(
            f"NSL v0.2 {owner} dependency inventory is invalid"
        )
    try:
        return tuple(Requirement(str(item)) for item in value)
    except InvalidRequirement as exc:
        raise NslPackageAdmissionError(
            f"NSL v0.2 {owner} dependency inventory is invalid"
        ) from exc
