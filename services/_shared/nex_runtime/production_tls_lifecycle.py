from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from .production_startup_admission import admit_production_startup


PRODUCTION_TLS_LIFECYCLE_SCHEMA_VERSION = "production_tls_lifecycle.v1"
TLS_ROTATION_PHASES = ("ISSUE", "STAGE", "OVERLAP_VERIFY", "ACTIVATE", "RETIRE")
TLS_ROLLBACK_PHASES = ("DEACTIVATE_CANDIDATE", "RESTORE_CURRENT", "VERIFY_CURRENT")
MINIMUM_VERIFICATION_OVERLAP = timedelta(hours=1)
EXPIRY_WARNING_WINDOW = timedelta(days=30)
EXPIRY_CRITICAL_WINDOW = timedelta(days=7)
_GENERATION = re.compile(r"^tls:[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")


class ProductionTlsLifecycleError(ValueError):
    pass


@dataclass(frozen=True)
class ManagedCertificateMetadata:
    certificate_id: str
    version: str
    state: str
    not_before: datetime
    not_after: datetime
    issuer_id: str
    dns_name_count: int
    private_key_exposed: bool = False


@dataclass(frozen=True)
class ProductionTlsLifecyclePlan:
    schema_version: str
    tls_generation: str
    termination_mode: str
    rotation_phases: tuple[str, ...]
    rollback_phases: tuple[str, ...]
    certificate_reference_version: str
    trust_bundle_reference_version: str
    application_private_key_mount_allowed: bool
    end_to_end_https_required: bool
    current: ManagedCertificateMetadata
    candidate: ManagedCertificateMetadata


@dataclass(frozen=True)
class ProductionTlsLifecycleDecision:
    status: str
    expiry_alert: str
    activate_candidate_approved: bool
    retire_current_approved: bool
    rollback_to_current_required: bool


def build_production_tls_lifecycle_plan(
    environ: Mapping[str, str],
    current: ManagedCertificateMetadata,
    candidate: ManagedCertificateMetadata,
    *,
    root: Path,
) -> ProductionTlsLifecyclePlan:
    admit_production_startup(environ, root=root)
    generation = str(environ["NEX_TLS_GENERATION"]).strip()
    certificate_version = _reference_version(
        str(environ["NEX_TLS_CERTIFICATE_REF"])
    )
    trust_version = _reference_version(str(environ["NEX_TLS_TRUST_BUNDLE_REF"]))
    errors = list(_certificate_errors(current, allowed_states={"ACTIVE"}))
    errors.extend(_certificate_errors(candidate, allowed_states={"CANDIDATE"}))
    if not _GENERATION.fullmatch(generation):
        errors.append("TLS generation is invalid")
    if current.certificate_id == candidate.certificate_id:
        errors.append("candidate certificate identity must change")
    if current.version == candidate.version:
        errors.append("candidate certificate version must change")
    if candidate.version != certificate_version:
        errors.append("candidate certificate reference version mismatch")
    try:
        overlap = _aware_utc(current.not_after) - _aware_utc(candidate.not_before)
    except (TypeError, ValueError):
        pass  # Both timestamp fields were already validated above.
    else:
        if overlap < MINIMUM_VERIFICATION_OVERLAP:
            errors.append("certificate overlap is too short")
    if errors:
        raise ProductionTlsLifecycleError("; ".join(errors))
    return ProductionTlsLifecyclePlan(
        schema_version=PRODUCTION_TLS_LIFECYCLE_SCHEMA_VERSION,
        tls_generation=generation,
        termination_mode="managed_ingress_or_service_mesh",
        rotation_phases=TLS_ROTATION_PHASES,
        rollback_phases=TLS_ROLLBACK_PHASES,
        certificate_reference_version=certificate_version,
        trust_bundle_reference_version=trust_version,
        application_private_key_mount_allowed=False,
        end_to_end_https_required=True,
        current=current,
        candidate=candidate,
    )


def evaluate_production_tls_lifecycle(
    plan: ProductionTlsLifecyclePlan,
    *,
    observed_at: datetime,
    activation_attempted: bool,
    candidate_probe_verified: bool,
    candidate_verified_at: datetime | None = None,
) -> ProductionTlsLifecycleDecision:
    _validate_plan(plan)
    now = _aware_utc(observed_at)
    alert = certificate_expiry_alert(plan.current, observed_at=now)
    if plan.current.state == "REVOKED" or now >= _aware_utc(plan.current.not_after):
        status = "BLOCKED_CURRENT_CERTIFICATE"
    elif not activation_attempted:
        status = "STAGED"
    elif (
        plan.candidate.state == "REVOKED"
        or now < _aware_utc(plan.candidate.not_before)
        or now >= _aware_utc(plan.candidate.not_after)
        or not candidate_probe_verified
    ):
        status = "ROLLBACK_REQUIRED"
    elif candidate_verified_at is None or (
        now - _aware_utc(candidate_verified_at) < MINIMUM_VERIFICATION_OVERLAP
    ):
        status = "OVERLAP_VERIFYING"
    else:
        status = "VERIFIED"
    return ProductionTlsLifecycleDecision(
        status=status,
        expiry_alert=alert,
        activate_candidate_approved=status in {"OVERLAP_VERIFYING", "VERIFIED"},
        retire_current_approved=status == "VERIFIED",
        rollback_to_current_required=status == "ROLLBACK_REQUIRED",
    )


def certificate_expiry_alert(
    certificate: ManagedCertificateMetadata,
    *,
    observed_at: datetime,
) -> str:
    remaining = _aware_utc(certificate.not_after) - _aware_utc(observed_at)
    if remaining <= timedelta(0):
        return "EXPIRED"
    if remaining <= EXPIRY_CRITICAL_WINDOW:
        return "CRITICAL"
    if remaining <= EXPIRY_WARNING_WINDOW:
        return "WARNING"
    return "OK"


def production_tls_lifecycle_projection(
    plan: ProductionTlsLifecyclePlan,
    decision: ProductionTlsLifecycleDecision,
) -> dict[str, Any]:
    _validate_plan(plan)
    if decision.status not in {
        "STAGED",
        "OVERLAP_VERIFYING",
        "VERIFIED",
        "ROLLBACK_REQUIRED",
        "BLOCKED_CURRENT_CERTIFICATE",
    }:
        raise ProductionTlsLifecycleError("TLS lifecycle decision is invalid")
    return {
        "schema_version": plan.schema_version,
        "tls_generation": plan.tls_generation,
        "termination_mode": plan.termination_mode,
        "rotation_phases": list(plan.rotation_phases),
        "rollback_phases": list(plan.rollback_phases),
        "certificate_reference_version": plan.certificate_reference_version,
        "trust_bundle_reference_version": plan.trust_bundle_reference_version,
        "application_private_key_mount_allowed": (
            plan.application_private_key_mount_allowed
        ),
        "end_to_end_https_required": plan.end_to_end_https_required,
        "current": _certificate_projection(plan.current),
        "candidate": _certificate_projection(plan.candidate),
        "status": decision.status,
        "expiry_alert": decision.expiry_alert,
        "activate_candidate_approved": decision.activate_candidate_approved,
        "retire_current_approved": decision.retire_current_approved,
        "rollback_to_current_required": decision.rollback_to_current_required,
        "certificate_pem_included": False,
        "private_key_material_included": False,
    }


def _certificate_projection(value: ManagedCertificateMetadata) -> dict[str, Any]:
    return {
        "certificate_id": value.certificate_id,
        "version": value.version,
        "state": value.state,
        "not_before": _aware_utc(value.not_before).isoformat().replace("+00:00", "Z"),
        "not_after": _aware_utc(value.not_after).isoformat().replace("+00:00", "Z"),
        "issuer_id": value.issuer_id,
        "dns_name_count": value.dns_name_count,
        "private_key_exposed": value.private_key_exposed,
    }


def _certificate_errors(
    value: ManagedCertificateMetadata,
    *,
    allowed_states: set[str],
) -> tuple[str, ...]:
    errors = []
    if not value.certificate_id or not value.version or not value.issuer_id:
        errors.append("certificate metadata is incomplete")
    if value.state not in allowed_states:
        errors.append("certificate state is invalid")
    if value.private_key_exposed:
        errors.append("application certificate private key exposure is prohibited")
    if value.dns_name_count < 1:
        errors.append("certificate DNS coverage is empty")
    try:
        valid_window = _aware_utc(value.not_after) > _aware_utc(value.not_before)
    except (TypeError, ValueError):
        errors.append("certificate validity timestamps are invalid")
    else:
        if not valid_window:
            errors.append("certificate validity window is invalid")
    return tuple(errors)


def _validate_plan(plan: ProductionTlsLifecyclePlan) -> None:
    if (
        plan.schema_version != PRODUCTION_TLS_LIFECYCLE_SCHEMA_VERSION
        or plan.termination_mode != "managed_ingress_or_service_mesh"
        or plan.rotation_phases != TLS_ROTATION_PHASES
        or plan.rollback_phases != TLS_ROLLBACK_PHASES
        or plan.application_private_key_mount_allowed
        or not plan.end_to_end_https_required
    ):
        raise ProductionTlsLifecycleError("TLS lifecycle plan is invalid")


def _reference_version(reference: str) -> str:
    parsed = urlsplit(reference)
    try:
        _, version = parsed.path.rsplit("@", 1)
    except ValueError:
        raise ProductionTlsLifecycleError("TLS reference version is invalid") from None
    if parsed.scheme != "tls" or not parsed.hostname or not version:
        raise ProductionTlsLifecycleError("TLS reference version is invalid")
    return version


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("certificate timestamp must be a datetime")
    if value.tzinfo is None:
        raise ValueError("certificate timestamp must include a timezone")
    return value.astimezone(UTC)
