"""Independent, hash-bound accounting allocation intent and authority lineage."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

ACCOUNTING_ALLOCATION_OPERATION = "FINANCE.COST_ALLOCATION.RUN"
ACCOUNTING_ALLOCATION_SCOPE = "finance:allocation:execute"
ACCOUNTING_ALLOCATION_WORK_INTENT_SCHEMA = "ae.accounting_allocation_work_intent.v1"
ACCOUNTING_ALLOCATION_AUTHORITY_SCHEMA = "ae.accounting_allocation_authority.v1"
ACCOUNTING_ALLOCATION_AUTHORITY_STAGE = "AUTHORIZED_FOR_ALLOCATION_RESOLUTION"

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_SOURCE_KINDS = frozenset(
    {
        "PAYROLL",
        "PURCHASE",
        "SERVICE",
        "SHARED_EXPENSE",
        "REVENUE",
        "FX_GAIN_LOSS",
        "OTHER",
    }
)
_PUBLICATION_TARGETS = frozenset({"IA_WORKSPACE", "ACCOUNTING_WORKSPACE"})
_JOB_TYPES = frozenset({"START_EXECUTION", "CONTINUE_EXECUTION"})
_JOB_STATES = frozenset({"QUEUED", "RUNNING", "DONE"})


class AccountingAllocationAuthorityError(RuntimeError):
    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(detail)


def build_accounting_allocation_work_intent(
    *,
    tenant_id: str,
    company_id: str,
    subject_id: str,
    execution_id: str,
    work_intent_id: str,
    journal_id: str,
    source_record_line_ref: str,
    source_kind: str,
    projects: Sequence[Mapping[str, Any]],
    source_ref: str,
    requested_at: str,
    publication_target: str,
    publication_target_ref: str,
) -> Mapping[str, Any]:
    """Build a product intent that is independent from Journal preparation state."""

    semantics = {
        "schema_version": ACCOUNTING_ALLOCATION_WORK_INTENT_SCHEMA,
        "operation": ACCOUNTING_ALLOCATION_OPERATION,
        "tenant_id": _scoped("tenant_id", tenant_id),
        "company_id": _uuid("company_id", company_id),
        "subject_id": _scoped("subject_id", subject_id),
        "execution_id": _uuid("execution_id", execution_id),
        "work_intent_id": _uuid("work_intent_id", work_intent_id),
        "journal_id": _uuid("journal_id", journal_id),
        "source_record_line_ref": _scoped(
            "source_record_line_ref", source_record_line_ref
        ),
        "source_kind": _choice("source_kind", source_kind, _SOURCE_KINDS),
        "projects": list(_projects(projects)),
        "source_ref": _scoped("source_ref", source_ref),
        "requested_at": _timestamp("requested_at", requested_at),
        "publication": {
            "target": _choice(
                "publication_target", publication_target, _PUBLICATION_TARGETS
            ),
            "target_ref": _scoped("publication_target_ref", publication_target_ref),
        },
    }
    replay_semantics = {
        key: item
        for key, item in semantics.items()
        if key not in {"work_intent_id", "requested_at"}
    }
    semantics["replay_identity"] = semantic_sha256_hash_ref(
        {"domain": "AE-ACCOUNTING-ALLOCATION-REPLAY-V1", **replay_semantics}
    )
    intent = {**semantics, "intent_hash": semantic_sha256_hash_ref(semantics)}
    return _freeze_work_intent(validate_accounting_allocation_work_intent(intent))


def validate_accounting_allocation_work_intent(value: object) -> dict[str, Any]:
    expected = {
        "schema_version",
        "operation",
        "tenant_id",
        "company_id",
        "subject_id",
        "execution_id",
        "work_intent_id",
        "journal_id",
        "source_record_line_ref",
        "source_kind",
        "projects",
        "source_ref",
        "requested_at",
        "publication",
        "replay_identity",
        "intent_hash",
    }
    record = _exact("work_intent", value, expected)
    if (
        record["schema_version"] != ACCOUNTING_ALLOCATION_WORK_INTENT_SCHEMA
        or record["operation"] != ACCOUNTING_ALLOCATION_OPERATION
    ):
        raise _invalid("Accounting allocation WorkIntent identity is unsupported.")
    for name in ("company_id", "execution_id", "work_intent_id", "journal_id"):
        record[name] = _uuid(name, record[name])
    for name in (
        "tenant_id",
        "subject_id",
        "source_ref",
        "source_record_line_ref",
    ):
        record[name] = _scoped(name, record[name])
    record["source_kind"] = _choice("source_kind", record["source_kind"], _SOURCE_KINDS)
    record["requested_at"] = _timestamp("requested_at", record["requested_at"])
    record["projects"] = list(_projects(record["projects"]))
    publication = _exact("publication", record["publication"], {"target", "target_ref"})
    publication["target"] = _choice(
        "publication.target", publication["target"], _PUBLICATION_TARGETS
    )
    publication["target_ref"] = _scoped(
        "publication.target_ref", publication["target_ref"]
    )
    record["publication"] = publication
    replay = _hash("replay_identity", record["replay_identity"])
    replay_semantics = {
        key: item
        for key, item in record.items()
        if key
        not in {"work_intent_id", "requested_at", "replay_identity", "intent_hash"}
    }
    expected_replay = semantic_sha256_hash_ref(
        {"domain": "AE-ACCOUNTING-ALLOCATION-REPLAY-V1", **replay_semantics}
    )
    if replay != expected_replay:
        raise _invalid("Accounting allocation replay identity drifted.")
    record["replay_identity"] = replay
    intent_hash = _hash("intent_hash", record["intent_hash"])
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "intent_hash"}
    )
    if intent_hash != expected_hash:
        raise _invalid("Accounting allocation WorkIntent hash drifted.")
    record["intent_hash"] = intent_hash
    return record


def build_accounting_allocation_authority_checkpoint(
    *,
    work_intent: Mapping[str, Any],
    authorization: Mapping[str, Any],
    runtime_job: Mapping[str, Any],
    existing_checkpoint: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Bind fresh OA authority to one independently scheduled allocation job."""

    intent = validate_accounting_allocation_work_intent(work_intent)
    oa = _authorization(authorization, intent=intent)
    job = _runtime_job(runtime_job, intent=intent)
    semantics = {
        "schema_version": ACCOUNTING_ALLOCATION_AUTHORITY_SCHEMA,
        "stage": ACCOUNTING_ALLOCATION_AUTHORITY_STAGE,
        "operation": ACCOUNTING_ALLOCATION_OPERATION,
        "tenant_id": intent["tenant_id"],
        "company_id": intent["company_id"],
        "subject_id": intent["subject_id"],
        "execution_id": intent["execution_id"],
        "work_intent_id": intent["work_intent_id"],
        "work_intent_hash": intent["intent_hash"],
        "replay_identity": intent["replay_identity"],
        "oa_authority": oa,
        "runtime_job": job,
        "publication": dict(intent["publication"]),
    }
    checkpoint = {
        **semantics,
        "authority_hash": semantic_sha256_hash_ref(semantics),
    }
    if existing_checkpoint is not None:
        existing = validate_accounting_allocation_authority_checkpoint(
            existing_checkpoint
        )
        if existing != checkpoint:
            raise AccountingAllocationAuthorityError(
                "ACCOUNTING_ALLOCATION_AUTHORITY_REPLAY_CONFLICT",
                "Existing accounting allocation authority differs from exact replay.",
            )
        return existing_checkpoint
    return _freeze_checkpoint(checkpoint)


def validate_accounting_allocation_authority_checkpoint(
    value: object,
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "stage",
        "operation",
        "tenant_id",
        "company_id",
        "subject_id",
        "execution_id",
        "work_intent_id",
        "work_intent_hash",
        "replay_identity",
        "oa_authority",
        "runtime_job",
        "publication",
        "authority_hash",
    }
    record = _exact("authority_checkpoint", value, expected)
    if (
        record["schema_version"] != ACCOUNTING_ALLOCATION_AUTHORITY_SCHEMA
        or record["stage"] != ACCOUNTING_ALLOCATION_AUTHORITY_STAGE
        or record["operation"] != ACCOUNTING_ALLOCATION_OPERATION
    ):
        raise _invalid("Accounting allocation authority checkpoint is unsupported.")
    for name in ("company_id", "execution_id", "work_intent_id"):
        record[name] = _uuid(name, record[name])
    for name in ("tenant_id", "subject_id"):
        record[name] = _scoped(name, record[name])
    for name in ("work_intent_hash", "replay_identity"):
        record[name] = _hash(name, record[name])
    record["oa_authority"] = _bound_authorization(record["oa_authority"])
    record["runtime_job"] = _bound_runtime_job(record["runtime_job"])
    publication = _exact("publication", record["publication"], {"target", "target_ref"})
    publication["target"] = _choice(
        "publication.target", publication["target"], _PUBLICATION_TARGETS
    )
    publication["target_ref"] = _scoped(
        "publication.target_ref", publication["target_ref"]
    )
    record["publication"] = publication
    authority_hash = _hash("authority_hash", record["authority_hash"])
    if authority_hash != semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "authority_hash"}
    ):
        raise _invalid("Accounting allocation authority hash drifted.")
    record["authority_hash"] = authority_hash
    return record


def _authorization(value: object, *, intent: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _denied("OA accounting allocation authority is unavailable.")
    scopes = value.get("scopes")
    if (
        value.get("active") is not True
        or value.get("tenant_id") != intent["tenant_id"]
        or value.get("subject_id") != intent["subject_id"]
        or isinstance(scopes, (str, bytes))
        or not isinstance(scopes, Sequence)
        or ACCOUNTING_ALLOCATION_SCOPE not in scopes
    ):
        raise _denied("OA denied current accounting allocation authority.")
    revision_hash = _hash("oa.revision_hash", value.get("revision_hash"))
    evaluated_at = _timestamp("oa.evaluated_at", value.get("evaluated_at"))
    return {
        "required_scope": ACCOUNTING_ALLOCATION_SCOPE,
        "revision_hash": revision_hash,
        "evaluated_at": evaluated_at,
    }


def _runtime_job(value: object, *, intent: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Accounting allocation RuntimeJob is unavailable.")
    if (
        value.get("execution_id") != intent["execution_id"]
        or value.get("job_type") not in _JOB_TYPES
        or value.get("state") not in _JOB_STATES
    ):
        raise _invalid("Accounting allocation RuntimeJob lineage is invalid.")
    return {
        "runtime_job_id": _scoped("runtime_job_id", value.get("runtime_job_id")),
        "job_type": str(value["job_type"]),
        "state": str(value["state"]),
        "dedup_key": _scoped("dedup_key", value.get("dedup_key")),
    }


def _bound_authorization(value: object) -> dict[str, Any]:
    record = _exact(
        "oa_authority",
        value,
        {"required_scope", "revision_hash", "evaluated_at"},
    )
    if record["required_scope"] != ACCOUNTING_ALLOCATION_SCOPE:
        raise _invalid("Bound OA accounting allocation scope drifted.")
    return {
        "required_scope": ACCOUNTING_ALLOCATION_SCOPE,
        "revision_hash": _hash("oa.revision_hash", record["revision_hash"]),
        "evaluated_at": _timestamp("oa.evaluated_at", record["evaluated_at"]),
    }


def _bound_runtime_job(value: object) -> dict[str, Any]:
    record = _exact(
        "runtime_job",
        value,
        {"runtime_job_id", "job_type", "state", "dedup_key"},
    )
    return {
        "runtime_job_id": _scoped("runtime_job_id", record["runtime_job_id"]),
        "job_type": _choice("runtime_job.job_type", record["job_type"], _JOB_TYPES),
        "state": _choice("runtime_job.state", record["state"], _JOB_STATES),
        "dedup_key": _scoped("runtime_job.dedup_key", record["dedup_key"]),
    }


def _projects(value: object) -> tuple[dict[str, str], ...]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or not 1 <= len(value) <= 64
    ):
        raise _invalid("Accounting allocation projects must contain 1..64 items.")
    projects: list[dict[str, str]] = []
    for item in value:
        project = _exact("project", item, {"project_code", "allocation_ratio"})
        code = project.get("project_code")
        if not isinstance(code, str) or _PROJECT_CODE.fullmatch(code) is None:
            raise _invalid("Accounting allocation project_code is invalid.")
        projects.append(
            {
                "project_code": code,
                "allocation_ratio": _ratio(project.get("allocation_ratio")),
            }
        )
    projects.sort(key=lambda item: item["project_code"])
    if len({item["project_code"] for item in projects}) != len(projects):
        raise _invalid("Accounting allocation Project codes must be unique.")
    if sum((Decimal(item["allocation_ratio"]) for item in projects), Decimal()) != 1:
        raise _invalid("Accounting allocation ratios must total exactly one.")
    return tuple(projects)


def _ratio(value: object) -> str:
    try:
        number = Decimal(str(value)).quantize(Decimal("0.000000000001"))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid("Accounting allocation ratio is invalid.") from exc
    if not number.is_finite() or number <= 0 or number > 1:
        raise _invalid("Accounting allocation ratio is invalid.")
    return format(number, ".12f")


def _exact(field: str, value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid(f"{field} fields are not canonical.")
    return dict(value)


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _scoped(field: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field} is invalid.")
    return value


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(f"{field} is invalid.")
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} is invalid.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} is invalid.")
    return value


def _freeze_work_intent(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            **value,
            "projects": tuple(
                MappingProxyType(dict(item)) for item in value["projects"]
            ),
            "publication": MappingProxyType(dict(value["publication"])),
        }
    )


def _freeze_checkpoint(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            **value,
            "oa_authority": MappingProxyType(dict(value["oa_authority"])),
            "runtime_job": MappingProxyType(dict(value["runtime_job"])),
            "publication": MappingProxyType(dict(value["publication"])),
        }
    )


def _invalid(detail: str) -> AccountingAllocationAuthorityError:
    return AccountingAllocationAuthorityError(
        "ACCOUNTING_ALLOCATION_AUTHORITY_INVALID", detail
    )


def _denied(detail: str) -> AccountingAllocationAuthorityError:
    return AccountingAllocationAuthorityError(
        "ACCOUNTING_ALLOCATION_AUTHORITY_DENIED", detail
    )
