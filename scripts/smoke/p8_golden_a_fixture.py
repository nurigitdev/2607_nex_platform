from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_ORG_UNIT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    AccountInput,
    EosApproverResolutionService,
    NvtProjectInput,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    ProjectInput,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json"
FIXTURE_SCHEMA_VERSION = "p8_golden_a_fixture.v1"
ACTIVATION_STATE = "LOCKED_PENDING_P8_S64"
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "fixture_id",
    "fixture_hash",
    "tenant",
    "principals",
    "organization",
    "projects",
    "accounts",
    "voucher_line_policy",
    "admission",
    "approval_target",
    "scenario",
}
_FORBIDDEN_KEY = re.compile(
    r"(^|_)(password|passwd|secret|private_key|access_token|refresh_token|api_key)($|_)",
    re.IGNORECASE,
)


class GoldenAFixtureError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(detail)


class MembershipRegistry(Protocol):
    def ensure_membership(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


class OrganizationRepository(Protocol):
    def create_org_unit(self, value: OrgUnitInput) -> dict[str, Any]: ...

    def create_position(self, value: PositionInput) -> dict[str, Any]: ...

    def assign_position(self, value: PositionAssignmentInput) -> dict[str, Any]: ...

    def resolve_active_approver_assignment(
        self, **kwargs: Any
    ) -> dict[str, Any] | None: ...


class ProjectRepository(Protocol):
    def create_nvt_project(self, value: NvtProjectInput) -> dict[str, Any]: ...

    def create_project(self, value: ProjectInput) -> dict[str, Any]: ...

    def list_projects_for_nvt(self, **kwargs: Any) -> list[dict[str, Any]]: ...


class AccountRepository(Protocol):
    def create_account(self, value: AccountInput) -> dict[str, Any]: ...

    def get_effective_account(self, **kwargs: Any) -> dict[str, Any] | None: ...


def load_golden_a_fixture(
    path: Path = DEFAULT_FIXTURE_PATH,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenAFixtureError(
            "P8_GOLDEN_A_FIXTURE_UNREADABLE",
            f"Golden A fixture cannot be read: {path}",
        ) from exc
    return validate_golden_a_fixture(payload, root=root)


def validate_golden_a_fixture(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _TOP_LEVEL_FIELDS:
        raise _invalid("fixture must contain exactly the canonical top-level fields")
    record = deepcopy(dict(payload))
    _reject_private_keys(record)
    if record["schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise _invalid("schema_version is unsupported")
    _scoped_id("fixture_id", record["fixture_id"])
    supplied_hash = validate_hash_ref(record["fixture_hash"])
    hash_input = deepcopy(record)
    hash_input.pop("fixture_hash")
    if semantic_sha256_hash_ref(hash_input) != supplied_hash:
        raise GoldenAFixtureError(
            "P8_GOLDEN_A_FIXTURE_HASH_MISMATCH",
            "fixture_hash does not match the canonical fixture payload",
        )

    tenant = _mapping("tenant", record["tenant"], {"tenant_id", "display_name"})
    tenant_id = _scoped_id("tenant.tenant_id", tenant["tenant_id"])
    _text("tenant.display_name", tenant["display_name"])

    principals = _object_list("principals", record["principals"])
    principal_ids: set[str] = set()
    for index, principal in enumerate(principals):
        _exact_fields(
            f"principals[{index}]",
            principal,
            {"subject_id", "display_name", "roles", "scopes"},
        )
        subject_id = _scoped_id(
            f"principals[{index}].subject_id", principal["subject_id"]
        )
        if subject_id in principal_ids:
            raise _invalid("principal subject_id values must be unique")
        principal_ids.add(subject_id)
        _text(f"principals[{index}].display_name", principal["display_name"])
        _string_list(f"principals[{index}].roles", principal["roles"])
        _string_list(f"principals[{index}].scopes", principal["scopes"])

    organization = _mapping(
        "organization",
        record["organization"],
        {"effective_from", "units", "positions", "assignments"},
    )
    effective_from = _datetime(
        "organization.effective_from", organization["effective_from"]
    )
    units = _object_list("organization.units", organization["units"])
    unit_ids: set[str] = set()
    for index, unit in enumerate(units):
        _exact_fields(
            f"organization.units[{index}]",
            unit,
            {
                "org_unit_id",
                "org_unit_code",
                "name",
                "org_unit_type",
                "parent_org_unit_id",
            },
        )
        unit_id = _uuid(f"organization.units[{index}].org_unit_id", unit["org_unit_id"])
        if unit_id in unit_ids:
            raise _invalid("organization unit ids must be unique")
        parent_id = unit["parent_org_unit_id"]
        if (
            parent_id is not None
            and _uuid(f"organization.units[{index}].parent_org_unit_id", parent_id)
            not in unit_ids
        ):
            raise _invalid("organization parents must precede their children")
        unit_ids.add(unit_id)
        _text(f"organization.units[{index}].org_unit_code", unit["org_unit_code"])
        _text(f"organization.units[{index}].name", unit["name"])
        if unit["org_unit_type"] not in {"COMPANY", "GROUP", "TEAM", "PART"}:
            raise _invalid("organization unit type is unsupported")

    positions = _object_list("organization.positions", organization["positions"])
    position_ids: set[str] = set()
    for index, position in enumerate(positions):
        _exact_fields(
            f"organization.positions[{index}]",
            position,
            {"position_id", "position_type", "org_unit_id"},
        )
        position_id = _uuid(
            f"organization.positions[{index}].position_id", position["position_id"]
        )
        if position_id in position_ids:
            raise _invalid("organization position ids must be unique")
        position_ids.add(position_id)
        if (
            _uuid(
                f"organization.positions[{index}].org_unit_id", position["org_unit_id"]
            )
            not in unit_ids
        ):
            raise _invalid("position must reference a fixture organization unit")

    assignments = _object_list("organization.assignments", organization["assignments"])
    assignment_ids: set[str] = set()
    for index, assignment in enumerate(assignments):
        _exact_fields(
            f"organization.assignments[{index}]",
            assignment,
            {"position_assignment_id", "position_id", "principal_id"},
        )
        assignment_id = _uuid(
            f"organization.assignments[{index}].position_assignment_id",
            assignment["position_assignment_id"],
        )
        if assignment_id in assignment_ids:
            raise _invalid("organization assignment ids must be unique")
        assignment_ids.add(assignment_id)
        if (
            _uuid(
                f"organization.assignments[{index}].position_id",
                assignment["position_id"],
            )
            not in position_ids
        ):
            raise _invalid("assignment must reference a fixture position")
        if (
            _scoped_id(
                f"organization.assignments[{index}].principal_id",
                assignment["principal_id"],
            )
            not in principal_ids
        ):
            raise _invalid("assignment must reference a fixture principal")

    projects = _mapping("projects", record["projects"], {"nvt", "mother", "child"})
    nvt = _mapping(
        "projects.nvt", projects["nvt"], {"nvt_project_id", "nvt_project_code", "name"}
    )
    mother = _mapping(
        "projects.mother",
        projects["mother"],
        {"project_id", "project_code", "name", "nvt_project_id"},
    )
    child = _mapping(
        "projects.child",
        projects["child"],
        {"project_id", "project_code", "name", "parent_project_id"},
    )
    nvt_id = _uuid("projects.nvt.nvt_project_id", nvt["nvt_project_id"])
    mother_id = _uuid("projects.mother.project_id", mother["project_id"])
    child_id = _uuid("projects.child.project_id", child["project_id"])
    if mother_id == child_id:
        raise _invalid("mother and child project ids must differ")
    if _uuid("projects.mother.nvt_project_id", mother["nvt_project_id"]) != nvt_id:
        raise _invalid("mother project must reference the fixture NVTProject")
    if (
        _uuid("projects.child.parent_project_id", child["parent_project_id"])
        != mother_id
    ):
        raise _invalid("child project must reference the fixture Mother Project")
    for field_name, value in (
        ("projects.nvt.nvt_project_code", nvt["nvt_project_code"]),
        ("projects.mother.project_code", mother["project_code"]),
        ("projects.child.project_code", child["project_code"]),
        ("projects.nvt.name", nvt["name"]),
        ("projects.mother.name", mother["name"]),
        ("projects.child.name", child["name"]),
    ):
        _text(field_name, value)

    accounts = _object_list("accounts", record["accounts"])
    account_ids: set[str] = set()
    for index, account in enumerate(accounts):
        _exact_fields(
            f"accounts[{index}]",
            account,
            {
                "account_id",
                "account_code",
                "name",
                "category",
                "account_type",
                "effective_from",
            },
        )
        account_id = _uuid(f"accounts[{index}].account_id", account["account_id"])
        if account_id in account_ids:
            raise _invalid("account ids must be unique")
        account_ids.add(account_id)
        _text(f"accounts[{index}].account_code", account["account_code"])
        _text(f"accounts[{index}].name", account["name"])
        _date(f"accounts[{index}].effective_from", account["effective_from"])

    policy = _mapping(
        "voucher_line_policy",
        record["voucher_line_policy"],
        {
            "policy_id",
            "policy_version",
            "voucher_type",
            "economic_category",
            "settlement_method",
            "currency",
            "effective_from",
            "debit_account_id",
            "credit_account_id",
            "line_order",
        },
    )
    _scoped_id("voucher_line_policy.policy_id", policy["policy_id"])
    if policy["policy_version"] != 1 or policy["line_order"] != ["DEBIT", "CREDIT"]:
        raise _invalid("voucher line policy version or line order is unsupported")
    debit_id = _uuid("voucher_line_policy.debit_account_id", policy["debit_account_id"])
    credit_id = _uuid(
        "voucher_line_policy.credit_account_id", policy["credit_account_id"]
    )
    if debit_id == credit_id or {debit_id, credit_id} - account_ids:
        raise _invalid(
            "voucher line policy must reference two distinct fixture accounts"
        )
    policy_date = _date("voucher_line_policy.effective_from", policy["effective_from"])

    admission = _mapping(
        "admission",
        record["admission"],
        {
            "agent_id",
            "capability_id",
            "skill_id",
            "exact_skill_version",
            "skill_semantic_hash",
            "executor_kind",
            "operation_semantics",
            "backend_profile",
            "tool_id",
            "approval_id",
            "nsl_lock_path",
            "nsl_package_version",
            "nsl_wheel_sha256",
            "required_public_api_symbols",
            "activation_state",
        },
    )
    if admission["activation_state"] != ACTIVATION_STATE:
        raise _invalid("Golden A WRITE activation must remain deferred to P8-S64")
    if admission["operation_semantics"] != "WRITE":
        raise _invalid("Golden A admission must declare WRITE semantics")
    validate_hash_ref(admission["skill_semantic_hash"])
    _validate_nsl_lock(admission, root=root)

    target = _mapping(
        "approval_target",
        record["approval_target"],
        {
            "approval_domain",
            "risk_level",
            "policy_ref",
            "org_unit_id",
            "approver_subject_id",
            "position_type",
        },
    )
    target_unit = _uuid("approval_target.org_unit_id", target["org_unit_id"])
    target_subject = _scoped_id(
        "approval_target.approver_subject_id", target["approver_subject_id"]
    )
    if target_unit not in unit_ids or target_subject not in principal_ids:
        raise _invalid(
            "approval target must reference fixture organization and principal data"
        )
    matching_positions = {
        position["position_id"]
        for position in positions
        if position["org_unit_id"] == target_unit
        and position["position_type"] == target["position_type"]
    }
    if not any(
        assignment["position_id"] in matching_positions
        and assignment["principal_id"] == target_subject
        for assignment in assignments
    ):
        raise _invalid("approval target must have a matching position assignment")

    scenario = _mapping(
        "scenario",
        record["scenario"],
        {
            "requester_subject_id",
            "prompt",
            "amount",
            "currency",
            "transaction_date",
            "voucher_type",
            "economic_category",
            "settlement_method",
            "description",
            "attachments",
        },
    )
    requester = _scoped_id(
        "scenario.requester_subject_id", scenario["requester_subject_id"]
    )
    if requester not in principal_ids or requester == target_subject:
        raise _invalid("requester must be a distinct fixture principal")
    _text("scenario.prompt", scenario["prompt"])
    _text("scenario.description", scenario["description"])
    scenario_date = _date("scenario.transaction_date", scenario["transaction_date"])
    if policy_date > scenario_date:
        raise _invalid("voucher line policy is not effective for the scenario")
    for field in ("currency", "voucher_type", "economic_category", "settlement_method"):
        if scenario[field] != policy[field]:
            raise _invalid(
                f"scenario.{field} must match the deterministic voucher line policy"
            )
    if not re.fullmatch(r"[1-9][0-9]*\.[0-9]{2}", str(scenario["amount"])):
        raise _invalid("scenario.amount must be a positive two-decimal string")
    if scenario["attachments"] != []:
        raise _invalid("Golden A baseline keeps attachments optional and empty")
    if tenant_id != "p8-golden-a" or effective_from > datetime.combine(
        scenario_date, datetime.min.time(), tzinfo=UTC
    ):
        raise _invalid(
            "fixture tenant or effective period is not the protected baseline"
        )
    return record


def seed_golden_a_fixture(
    fixture: Mapping[str, Any],
    *,
    memberships: MembershipRegistry,
    organization: OrganizationRepository,
    projects: ProjectRepository,
    accounts: AccountRepository,
    root: Path = ROOT,
) -> dict[str, Any]:
    record = validate_golden_a_fixture(fixture, root=root)
    tenant = record["tenant"]
    tenant_id = tenant["tenant_id"]
    effective_from = _datetime(
        "organization.effective_from", record["organization"]["effective_from"]
    )
    effective_date = _date(
        "scenario.transaction_date", record["scenario"]["transaction_date"]
    )

    for principal in record["principals"]:
        memberships.ensure_membership(
            {
                "tenant_id": tenant_id,
                "tenant_display_name": tenant["display_name"],
                "subject_id": principal["subject_id"],
                "subject_display_name": principal["display_name"],
                "roles": principal["roles"],
                "scopes": principal["scopes"],
                "membership_metadata": {"fixture_id": record["fixture_id"]},
            }
        )

    for unit in record["organization"]["units"]:
        organization.create_org_unit(
            OrgUnitInput(
                tenant_id=tenant_id,
                effective_from=effective_from,
                **unit,
            )
        )
    for position in record["organization"]["positions"]:
        organization.create_position(PositionInput(tenant_id=tenant_id, **position))
    for assignment in record["organization"]["assignments"]:
        organization.assign_position(
            PositionAssignmentInput(
                tenant_id=tenant_id,
                position_assignment_id=assignment["position_assignment_id"],
                position_id=assignment["position_id"],
                principal_ref={"type": "oa.user", "id": assignment["principal_id"]},
                effective_from=effective_from,
            )
        )

    nvt = record["projects"]["nvt"]
    mother = record["projects"]["mother"]
    child = record["projects"]["child"]
    projects.create_nvt_project(NvtProjectInput(tenant_id=tenant_id, **nvt))
    projects.create_project(ProjectInput(tenant_id=tenant_id, **mother))
    projects.create_project(ProjectInput(tenant_id=tenant_id, **child))
    for account in record["accounts"]:
        accounts.create_account(
            AccountInput(
                tenant_id=tenant_id,
                account_id=account["account_id"],
                account_code=account["account_code"],
                name=account["name"],
                category=account["category"],
                account_type=account["account_type"],
                effective_from=_date(
                    "account.effective_from", account["effective_from"]
                ),
            )
        )

    project_rows = projects.list_projects_for_nvt(
        tenant_id=tenant_id,
        nvt_project_id=nvt["nvt_project_id"],
    )
    policy = record["voucher_line_policy"]
    effective_accounts = [
        accounts.get_effective_account(
            tenant_id=tenant_id,
            account_id=account_id,
            effective_at=effective_date,
        )
        for account_id in (policy["debit_account_id"], policy["credit_account_id"])
    ]
    if [row["hierarchy_depth"] for row in project_rows] != [1, 2]:
        raise GoldenAFixtureError(
            "P8_GOLDEN_A_SEED_VERIFICATION_FAILED",
            "Golden A project hierarchy did not persist at depths 1 and 2",
        )
    if any(account is None for account in effective_accounts):
        raise GoldenAFixtureError(
            "P8_GOLDEN_A_SEED_VERIFICATION_FAILED",
            "Golden A account set is not effective for the scenario date",
        )

    target = record["approval_target"]
    resolution = EosApproverResolutionService(
        organization,
        clock=lambda: effective_from,
    ).resolve(
        {
            "schema_version": "eos_approver_resolution_request.v1",
            "requester_ref": {
                "type": "oa.user",
                "id": record["scenario"]["requester_subject_id"],
            },
            "approval_domain": target["approval_domain"],
            "risk_level": target["risk_level"],
            "org_unit_ref": {"type": "eos.org_unit", "id": target["org_unit_id"]},
            "project_ref": {"type": "eos.project", "id": child["project_id"]},
            "policy_ref": target["policy_ref"],
        },
        tenant_id=tenant_id,
    )
    if resolution["principal_ref"]["id"] != target["approver_subject_id"]:
        raise GoldenAFixtureError(
            "P8_GOLDEN_A_SEED_VERIFICATION_FAILED",
            "Golden A approver resolution differs from the fixture target",
        )
    return golden_a_public_projection(
        record, resolution_hash=resolution["resolution_hash"]
    )


def golden_a_public_projection(
    fixture: Mapping[str, Any],
    *,
    resolution_hash: str | None = None,
) -> dict[str, Any]:
    record = validate_golden_a_fixture(fixture)
    projection: dict[str, Any] = {
        "schema_version": "p8_golden_a_seed_result.v1",
        "fixture_id": record["fixture_id"],
        "fixture_hash": record["fixture_hash"],
        "tenant_id": record["tenant"]["tenant_id"],
        "principal_ids": [item["subject_id"] for item in record["principals"]],
        "org_unit_ids": [
            item["org_unit_id"] for item in record["organization"]["units"]
        ],
        "project_ids": [
            record["projects"]["mother"]["project_id"],
            record["projects"]["child"]["project_id"],
        ],
        "account_ids": [item["account_id"] for item in record["accounts"]],
        "policy_id": record["voucher_line_policy"]["policy_id"],
        "skill_id": record["admission"]["skill_id"],
        "activation_state": record["admission"]["activation_state"],
        "approval_target_subject_id": record["approval_target"]["approver_subject_id"],
    }
    if resolution_hash is not None:
        projection["approval_resolution_hash"] = validate_hash_ref(resolution_hash)
    return projection


def reset_golden_a_fixture(
    fixture: Mapping[str, Any],
    *,
    oa_engine: Engine,
    eos_engine: Engine,
    root: Path = ROOT,
) -> dict[str, dict[str, int]]:
    record = validate_golden_a_fixture(fixture, root=root)
    tenant_id = record["tenant"]["tenant_id"]
    with eos_engine.begin() as connection:
        for table in (
            EOS_PROJECT_MEMBER_TABLE,
            EOS_POSITION_ASSIGNMENT_TABLE,
            EOS_POSITION_TABLE,
            EOS_ORG_UNIT_TABLE,
            EOS_ACCOUNT_TABLE,
            EOS_PROJECT_TABLE,
            EOS_NVT_PROJECT_TABLE,
        ):
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))
    with oa_engine.begin() as connection:
        for table_name in ("oa_tenant_memberships", "oa_subjects", "oa_tenants"):
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
    return golden_a_residue_counts(record, oa_engine=oa_engine, eos_engine=eos_engine)


def golden_a_residue_counts(
    fixture: Mapping[str, Any],
    *,
    oa_engine: Engine,
    eos_engine: Engine,
) -> dict[str, dict[str, int]]:
    tenant_id = fixture["tenant"]["tenant_id"]
    with oa_engine.connect() as connection:
        oa_counts = {
            table_name: int(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM {table_name} WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table_name in ("oa_tenants", "oa_subjects", "oa_tenant_memberships")
        }
    with eos_engine.connect() as connection:
        eos_counts = {
            table.name: int(
                connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.tenant_id == tenant_id)
                ).scalar_one()
            )
            for table in (
                EOS_NVT_PROJECT_TABLE,
                EOS_PROJECT_TABLE,
                EOS_PROJECT_MEMBER_TABLE,
                EOS_ACCOUNT_TABLE,
                EOS_ORG_UNIT_TABLE,
                EOS_POSITION_TABLE,
                EOS_POSITION_ASSIGNMENT_TABLE,
            )
        }
    return {"nex-oa": oa_counts, "nex-eos": eos_counts}


def _validate_nsl_lock(admission: Mapping[str, Any], *, root: Path) -> None:
    relative = Path(_text("admission.nsl_lock_path", admission["nsl_lock_path"]))
    lock_path = (root / relative).resolve()
    root = root.resolve()
    if not lock_path.is_relative_to(root) or not lock_path.is_file():
        raise _invalid("admission.nsl_lock_path must resolve to a tracked lock file")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid("admission NSL lock is unreadable") from exc
    required_symbols = set(
        _string_list(
            "admission.required_public_api_symbols",
            admission["required_public_api_symbols"],
        )
    )
    if (
        lock.get("schema_version") != "nsl_wheel_lock.v2"
        or lock.get("package_version") != admission["nsl_package_version"]
        or lock.get("wheel_sha256") != admission["nsl_wheel_sha256"]
        or not required_symbols.issubset(set(lock.get("public_api_symbols", [])))
    ):
        raise _invalid("admission does not match the admitted NSL v0.2 wheel lock")


def _mapping(name: str, value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be an object")
    result = dict(value)
    _exact_fields(name, result, fields)
    return result


def _exact_fields(name: str, value: Mapping[str, Any], fields: set[str]) -> None:
    if set(value) != fields:
        raise _invalid(f"{name} must contain exactly {sorted(fields)}")


def _object_list(name: str, value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise _invalid(f"{name} must be a non-empty array")
    if any(not isinstance(item, Mapping) for item in value):
        raise _invalid(f"{name} entries must be objects")
    return [dict(item) for item in value]


def _string_list(name: str, value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise _invalid(f"{name} must be a non-empty unique string array")
    return list(value)


def _scoped_id(name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", normalized) is None:
        raise _invalid(f"{name} has invalid stable-reference syntax")
    return normalized


def _uuid(name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{name} must be a UUID") from exc


def _text(name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise _invalid(f"{name} must be non-empty text")
    return normalized


def _date(name: str, value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be an ISO date") from exc


def _datetime(name: str, value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _reject_private_keys(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _FORBIDDEN_KEY.search(str(key)):
                raise GoldenAFixtureError(
                    "P8_GOLDEN_A_FIXTURE_PRIVATE_DATA",
                    f"private credential field is forbidden at {path}.{key}",
                )
            _reject_private_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_keys(item, path=f"{path}[{index}]")


def _invalid(detail: str) -> GoldenAFixtureError:
    return GoldenAFixtureError("P8_GOLDEN_A_FIXTURE_INVALID", detail)
