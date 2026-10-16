from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import importlib.metadata
import io
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from .semantic_hashes import semantic_sha256_hash_ref

NSL_WHEEL_ADMISSION_SCHEMA_VERSION = "nsl_wheel_admission.v1"
NSL_WHEEL_LOCK_SCHEMA_VERSION = "nsl_wheel_lock.v1"
NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION = "nsl_installed_package_readiness.v1"
NSL_DISTRIBUTION = "nex-skill-language"
NSL_PUBLIC_API_PATH = "nsl/api/__init__.py"
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_NSL_WHEEL_LOCK_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "distribution",
        "package_version",
        "source_revision",
        "wheel_filename",
        "wheel_sha256",
        "requires_python",
        "requirements",
        "platform_cryptography_requirement",
        "locked_cryptography_version",
        "platform_lock_sha256",
        "public_api_symbols",
    }
)


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


def inspect_installed_nsl_package(
    lock: Mapping[str, Any],
    *,
    platform_lock_path: Path,
    distribution_loader: Callable[[str], Any] | None = None,
    version_loader: Callable[[str], str] | None = None,
    module_loader: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Verify that the admitted NSL wheel is the active in-process package."""

    normalized = _validate_runtime_wheel_lock(lock)
    load_distribution = distribution_loader or importlib.metadata.distribution
    load_version = version_loader or importlib.metadata.version
    load_module = module_loader or importlib.import_module
    try:
        distribution = load_distribution(normalized["distribution"])
        installed_version = str(distribution.version)
        direct_url = json.loads(distribution.read_text("direct_url.json") or "")
        if not isinstance(direct_url, Mapping):
            raise TypeError("installed NSL direct URL evidence must be an object")
        cryptography_version = load_version("cryptography")
        api = load_module("nsl.api")
    except (
        importlib.metadata.PackageNotFoundError,
        ImportError,
        AttributeError,
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise NslPackageAdmissionError(
            "installed NSL package readiness evidence is unavailable"
        ) from exc

    errors: list[str] = []
    try:
        platform_lock_sha256 = _sha256_ref(platform_lock_path.read_bytes())
    except OSError as exc:
        raise NslPackageAdmissionError(
            "Platform dependency lock is unavailable"
        ) from exc
    if platform_lock_sha256 != normalized["platform_lock_sha256"]:
        errors.append("Platform dependency lock digest does not match NSL lock")
    if installed_version != normalized["package_version"]:
        errors.append("installed NSL package version does not match lock")
    if cryptography_version != normalized["locked_cryptography_version"]:
        errors.append("installed cryptography version does not match lock")

    archive_info = direct_url.get("archive_info")
    hashes = archive_info.get("hashes") if isinstance(archive_info, Mapping) else None
    archive_digest = hashes.get("sha256") if isinstance(hashes, Mapping) else None
    expected_digest = normalized["wheel_sha256"].removeprefix("sha256:")
    if archive_digest != expected_digest:
        errors.append("installed NSL wheel digest does not match lock")
    parsed_url = urlparse(str(direct_url.get("url", "")))
    wheel_filename = Path(unquote(parsed_url.path)).name
    if parsed_url.scheme != "file" or wheel_filename != normalized["wheel_filename"]:
        errors.append("installed NSL wheel origin does not match lock")

    api_file = getattr(api, "__file__", None)
    try:
        distribution_root = Path(distribution.locate_file("")).resolve()
        api_path = Path(api_file).resolve()
        imported_from_distribution = api_path.is_relative_to(distribution_root)
    except (OSError, TypeError, ValueError):
        imported_from_distribution = False
    if not imported_from_distribution:
        errors.append("NSL public API is not imported from installed distribution")
    public_api_symbols = normalized["public_api_symbols"]
    missing_symbols = sorted(
        symbol for symbol in public_api_symbols if not hasattr(api, symbol)
    )
    if missing_symbols:
        errors.append("installed NSL public API does not match lock")
    if errors:
        raise NslPackageAdmissionError("; ".join(errors))

    return {
        "schema_version": NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION,
        "status": "PASS",
        "distribution": normalized["distribution"],
        "package_version": installed_version,
        "source_revision": normalized["source_revision"],
        "wheel_filename": normalized["wheel_filename"],
        "wheel_sha256": normalized["wheel_sha256"],
        "locked_cryptography_version": cryptography_version,
        "platform_lock_sha256": platform_lock_sha256,
        "public_api_symbols": list(public_api_symbols),
        "public_api_complete": True,
        "runtime_import_origin": "installed_distribution",
        "admission_lock_hash": semantic_sha256_hash_ref(normalized),
        "in_process_profile_admissible": True,
    }


def _validate_runtime_wheel_lock(lock: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(lock, Mapping) or set(lock) != _NSL_WHEEL_LOCK_FIELDS:
        raise NslPackageAdmissionError("NSL wheel lock fields are invalid")
    normalized = dict(lock)
    if normalized["schema_version"] != NSL_WHEEL_LOCK_SCHEMA_VERSION:
        raise NslPackageAdmissionError("NSL wheel lock schema version is invalid")
    if canonicalize_name(str(normalized["distribution"])) != NSL_DISTRIBUTION:
        raise NslPackageAdmissionError("NSL wheel lock distribution is invalid")
    try:
        Version(str(normalized["package_version"]))
        Version(str(normalized["locked_cryptography_version"]))
    except InvalidVersion as exc:
        raise NslPackageAdmissionError("NSL wheel lock version is invalid") from exc
    if not _GIT_REVISION.fullmatch(str(normalized["source_revision"])):
        raise NslPackageAdmissionError("NSL wheel lock source revision is invalid")
    for field in ("wheel_sha256", "platform_lock_sha256"):
        if not _HASH_REF.fullmatch(str(normalized[field])):
            raise NslPackageAdmissionError(f"NSL wheel lock {field} is invalid")
    wheel_filename = normalized["wheel_filename"]
    if (
        not isinstance(wheel_filename, str)
        or Path(wheel_filename).name != wheel_filename
    ):
        raise NslPackageAdmissionError("NSL wheel lock filename is invalid")
    symbols = normalized["public_api_symbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(item, str) or not item for item in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise NslPackageAdmissionError("NSL wheel lock public API symbols are invalid")
    return normalized


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
