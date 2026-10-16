from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

NSL_WHEEL_ADMISSION_SCHEMA_VERSION = "nsl_wheel_admission.v1"
NSL_WHEEL_LOCK_SCHEMA_VERSION = "nsl_wheel_lock.v1"
NSL_DISTRIBUTION = "nex-skill-language"
NSL_PUBLIC_API_PATH = "nsl/api/__init__.py"
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


class NslPackageAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class NslWheelInspection:
    distribution: str
    version: str
    requires_python: str
    requirements: tuple[str, ...]
    wheel_filename: str
    wheel_sha256: str
    wheel_size: int
    record_file_count: int
    record_integrity_count: int


def inspect_nsl_wheel(path: Path) -> NslWheelInspection:
    if not path.is_file() or path.suffix != ".whl":
        raise NslPackageAdmissionError("NSL wheel is missing or has an invalid suffix")
    try:
        filename_name, filename_version, _, _ = parse_wheel_filename(path.name)
    except (ValueError, InvalidVersion) as exc:
        raise NslPackageAdmissionError("NSL wheel filename is invalid") from exc

    try:
        with ZipFile(path) as archive:
            names = tuple(item.filename for item in archive.infolist())
            _validate_member_paths(names)
            metadata_name = _single_member(names, ".dist-info/METADATA")
            wheel_name = _single_member(names, ".dist-info/WHEEL")
            record_name = _single_member(names, ".dist-info/RECORD")
            if NSL_PUBLIC_API_PATH not in names:
                raise NslPackageAdmissionError("NSL public API is missing from wheel")
            metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
            archive.read(wheel_name).decode("utf-8")
            record_count, integrity_count = _validate_record(
                archive, record_name, names
            )
    except (BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise NslPackageAdmissionError("NSL wheel archive is invalid") from exc

    distribution = metadata.get("Name", "")
    version = metadata.get("Version", "")
    requires_python = metadata.get("Requires-Python", "")
    requirements = tuple(metadata.get_all("Requires-Dist", ()))
    if canonicalize_name(distribution) != canonicalize_name(filename_name):
        raise NslPackageAdmissionError("NSL wheel name does not match METADATA")
    if Version(version) != filename_version:
        raise NslPackageAdmissionError("NSL wheel version does not match METADATA")
    for value in requirements:
        try:
            Requirement(value)
        except InvalidRequirement as exc:
            raise NslPackageAdmissionError(
                "NSL wheel contains an invalid dependency requirement"
            ) from exc
    return NslWheelInspection(
        distribution=distribution,
        version=version,
        requires_python=requires_python,
        requirements=requirements,
        wheel_filename=path.name,
        wheel_sha256=_sha256_ref(path.read_bytes()),
        wheel_size=path.stat().st_size,
        record_file_count=record_count,
        record_integrity_count=integrity_count,
    )


def build_nsl_wheel_admission(
    inspection: NslWheelInspection,
    *,
    source_revision: str,
    source_tree_clean: bool,
    expected_version: str,
    platform_cryptography_requirement: str,
    locked_cryptography_version: str,
    platform_lock_sha256: str,
    public_api_symbols: tuple[str, ...],
) -> dict[str, Any]:
    errors: list[str] = []
    if canonicalize_name(inspection.distribution) != NSL_DISTRIBUTION:
        errors.append("unexpected NSL distribution")
    if inspection.version != expected_version:
        errors.append("unexpected NSL package version")
    if inspection.requires_python != ">=3.12":
        errors.append("unexpected NSL Python requirement")
    if not _GIT_REVISION.fullmatch(source_revision):
        errors.append("invalid NSL source revision")
    if not source_tree_clean:
        errors.append("NSL source tree is not clean")
    if not _HASH_REF.fullmatch(platform_lock_sha256):
        errors.append("invalid Platform dependency lock digest")

    nsl_requirement = _single_requirement(
        inspection.requirements, "cryptography", errors
    )
    platform_requirement = _parsed_requirement(
        platform_cryptography_requirement, "Platform", errors
    )
    try:
        locked_version = Version(locked_cryptography_version)
    except InvalidVersion:
        errors.append("invalid locked cryptography version")
        locked_version = None
    if locked_version is not None:
        if (
            nsl_requirement is not None
            and locked_version not in nsl_requirement.specifier
        ):
            errors.append("locked cryptography version is outside NSL requirement")
        if (
            platform_requirement is not None
            and locked_version not in platform_requirement.specifier
        ):
            errors.append("locked cryptography version is outside Platform requirement")
    if not public_api_symbols:
        errors.append("NSL public API import evidence is empty")
    if errors:
        raise NslPackageAdmissionError("; ".join(errors))

    return {
        "schema_version": NSL_WHEEL_ADMISSION_SCHEMA_VERSION,
        "status": "PASS",
        "distribution": inspection.distribution,
        "package_version": inspection.version,
        "source_revision": source_revision,
        "source_tree_clean": source_tree_clean,
        "wheel_filename": inspection.wheel_filename,
        "wheel_sha256": inspection.wheel_sha256,
        "wheel_size": inspection.wheel_size,
        "requires_python": inspection.requires_python,
        "requirements": list(inspection.requirements),
        "record_file_count": inspection.record_file_count,
        "record_integrity_count": inspection.record_integrity_count,
        "platform_cryptography_requirement": str(platform_requirement),
        "locked_cryptography_version": str(locked_version),
        "platform_lock_sha256": platform_lock_sha256,
        "public_api_symbols": list(public_api_symbols),
        "decision": {
            "dependency_compatible": True,
            "wheel_integrity_verified": True,
            "public_api_imported_from_wheel": True,
            "in_process_profile_admissible": True,
        },
    }


def nsl_wheel_lock_projection(
    admission: dict[str, Any], *, repository: str
) -> dict[str, Any]:
    if admission.get("status") != "PASS":
        raise NslPackageAdmissionError("only passing admission can be locked")
    return {
        "schema_version": NSL_WHEEL_LOCK_SCHEMA_VERSION,
        "repository": repository,
        "distribution": admission["distribution"],
        "package_version": admission["package_version"],
        "source_revision": admission["source_revision"],
        "wheel_filename": admission["wheel_filename"],
        "wheel_sha256": admission["wheel_sha256"],
        "requires_python": admission["requires_python"],
        "requirements": admission["requirements"],
        "platform_cryptography_requirement": admission[
            "platform_cryptography_requirement"
        ],
        "locked_cryptography_version": admission["locked_cryptography_version"],
        "platform_lock_sha256": admission["platform_lock_sha256"],
        "public_api_symbols": admission["public_api_symbols"],
    }


def validate_nsl_wheel_lock(
    admission: dict[str, Any], lock: dict[str, Any], *, repository: str
) -> None:
    expected = nsl_wheel_lock_projection(admission, repository=repository)
    if lock != expected:
        raise NslPackageAdmissionError("NSL wheel lock does not match admission")


def _validate_member_paths(names: tuple[str, ...]) -> None:
    if not names or len(set(names)) != len(names):
        raise NslPackageAdmissionError("NSL wheel member inventory is invalid")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise NslPackageAdmissionError("NSL wheel contains an unsafe path")


def _single_member(names: tuple[str, ...], suffix: str) -> str:
    matches = tuple(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        raise NslPackageAdmissionError(f"NSL wheel requires one {suffix}")
    return matches[0]


def _validate_record(
    archive: ZipFile, record_name: str, names: tuple[str, ...]
) -> tuple[int, int]:
    rows = tuple(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    paths: set[str] = set()
    integrity_count = 0
    for row in rows:
        if len(row) != 3 or row[0] in paths or row[0] not in names:
            raise NslPackageAdmissionError("NSL wheel RECORD inventory is invalid")
        paths.add(row[0])
        if row[0] == record_name:
            if row[1] or row[2]:
                raise NslPackageAdmissionError("NSL wheel RECORD self-entry is invalid")
            continue
        payload = archive.read(row[0])
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(
            b"="
        )
        if row[1] != f"sha256={encoded.decode('ascii')}" or row[2] != str(len(payload)):
            raise NslPackageAdmissionError("NSL wheel RECORD digest mismatch")
        integrity_count += 1
    if paths != set(names):
        raise NslPackageAdmissionError("NSL wheel RECORD coverage is incomplete")
    return len(rows), integrity_count


def _single_requirement(
    requirements: tuple[str, ...], name: str, errors: list[str]
) -> Requirement | None:
    matches: list[Requirement] = []
    for value in requirements:
        requirement = _parsed_requirement(value, "NSL", errors)
        if requirement is not None and canonicalize_name(requirement.name) == name:
            matches.append(requirement)
    if len(matches) != 1:
        errors.append(f"NSL wheel requires one {name} dependency")
        return None
    return matches[0]


def _parsed_requirement(
    value: str, owner: str, errors: list[str]
) -> Requirement | None:
    try:
        return Requirement(value)
    except InvalidRequirement:
        errors.append(f"invalid {owner} dependency requirement")
        return None


def _sha256_ref(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
