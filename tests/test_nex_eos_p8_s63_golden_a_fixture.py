from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from nex_eos import (
    EOS_METADATA,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from p8_golden_a_fixture import (
    ACTIVATION_STATE,
    GoldenAFixtureError,
    golden_a_public_projection,
    load_golden_a_fixture,
    reset_golden_a_fixture,
    seed_golden_a_fixture,
    validate_golden_a_fixture,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]


def _fixture() -> dict:
    return load_golden_a_fixture()


def _rehash(payload: dict) -> dict:
    payload = deepcopy(payload)
    payload.pop("fixture_hash", None)
    payload["fixture_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _eos_repositories():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return (
        engine,
        SqlAlchemyEosOrganizationRepository(factory),
        SqlAlchemyEosProjectRepository(factory),
        SqlAlchemyEosAccountRepository(factory),
    )


def test_canonical_fixture_is_hashed_locked_and_safe_to_publish() -> None:
    fixture = _fixture()
    projection = golden_a_public_projection(fixture)

    assert fixture["schema_version"] == "p8_golden_a_fixture.v1"
    assert fixture["admission"]["activation_state"] == ACTIVATION_STATE
    assert fixture["admission"]["nsl_package_version"] == "0.2.0"
    assert projection["tenant_id"] == "p8-golden-a"
    assert projection["project_ids"][-1] == ("82000000-0000-4000-8000-000000000001")
    assert projection["account_ids"] == [
        "83000000-0000-4000-8000-000000000001",
        "83000000-0000-4000-8000-000000000002",
    ]
    serialized = str(projection).lower()
    assert "prompt" not in serialized
    assert "password" not in serialized
    assert "api_key" not in serialized


def test_seed_is_deterministic_across_independent_stores() -> None:
    fixture = _fixture()
    results = []
    for _ in range(2):
        engine, organization, projects, accounts = _eos_repositories()
        try:
            result = seed_golden_a_fixture(
                fixture,
                memberships=InMemoryOaTenantMembershipRegistry(),
                organization=organization,
                projects=projects,
                accounts=accounts,
            )
            results.append(result)
            assert [
                row["hierarchy_depth"]
                for row in projects.list_projects_for_nvt(
                    tenant_id="p8-golden-a",
                    nvt_project_id="81000000-0000-4000-8000-000000000001",
                )
            ] == [1, 2]
        finally:
            engine.dispose()

    assert results[0] == results[1]
    assert results[0]["approval_target_subject_id"] == "employee-2001"
    assert results[0]["approval_resolution_hash"].startswith("sha256:")


def test_reset_removes_eos_and_oa_fixture_residue() -> None:
    fixture = _fixture()
    eos_engine, organization, projects, accounts = _eos_repositories()
    seed_golden_a_fixture(
        fixture,
        memberships=InMemoryOaTenantMembershipRegistry(),
        organization=organization,
        projects=projects,
        accounts=accounts,
    )
    oa_engine = create_engine("sqlite+pysqlite:///:memory:")
    with oa_engine.begin() as connection:
        for table_name in ("oa_tenants", "oa_subjects", "oa_tenant_memberships"):
            connection.execute(
                text(f"CREATE TABLE {table_name} (tenant_id TEXT NOT NULL)")
            )
            connection.execute(
                text(f"INSERT INTO {table_name} (tenant_id) VALUES (:tenant_id)"),
                {"tenant_id": "p8-golden-a"},
            )
    try:
        counts = reset_golden_a_fixture(
            fixture,
            oa_engine=oa_engine,
            eos_engine=eos_engine,
        )
    finally:
        oa_engine.dispose()
        eos_engine.dispose()

    assert all(value == 0 for service in counts.values() for value in service.values())


def test_loader_reports_unreadable_and_hash_mismatch(tmp_path: Path) -> None:
    with pytest.raises(GoldenAFixtureError) as unreadable:
        load_golden_a_fixture(tmp_path / "missing.json")
    assert unreadable.value.error_code == "P8_GOLDEN_A_FIXTURE_UNREADABLE"

    payload = _fixture()
    payload["scenario"]["amount"] = "1.00"
    with pytest.raises(GoldenAFixtureError) as mismatch:
        validate_golden_a_fixture(payload)
    assert mismatch.value.error_code == "P8_GOLDEN_A_FIXTURE_HASH_MISMATCH"


@pytest.mark.parametrize(
    ("mutator", "detail"),
    (
        (
            lambda value: value["principals"].append(deepcopy(value["principals"][0])),
            "principal subject_id values must be unique",
        ),
        (
            lambda value: value["projects"]["child"].update(
                {"parent_project_id": "82000000-0000-4000-8000-000000000009"}
            ),
            "child project must reference",
        ),
        (
            lambda value: value["scenario"].update({"currency": "USD"}),
            "scenario.currency must match",
        ),
        (
            lambda value: value["admission"].update({"activation_state": "ACTIVE"}),
            "activation must remain deferred",
        ),
        (
            lambda value: value["scenario"].update(
                {"requester_subject_id": "employee-2001"}
            ),
            "requester must be a distinct",
        ),
        (
            lambda value: value["voucher_line_policy"].update(
                {"credit_account_id": value["voucher_line_policy"]["debit_account_id"]}
            ),
            "two distinct fixture accounts",
        ),
        (
            lambda value: value["admission"].update(
                {"nsl_lock_path": "deployment/locks/missing.json"}
            ),
            "tracked lock file",
        ),
        (
            lambda value: value["admission"]["required_public_api_symbols"].append(
                "MissingPublicSymbol"
            ),
            "does not match the admitted",
        ),
    ),
)
def test_cross_reference_and_admission_validation_fails_closed(mutator, detail) -> None:
    payload = _fixture()
    mutator(payload)
    payload = _rehash(payload)

    with pytest.raises(GoldenAFixtureError, match=detail) as failure:
        validate_golden_a_fixture(payload)

    assert failure.value.error_code == "P8_GOLDEN_A_FIXTURE_INVALID"


def test_fixture_rejects_private_fields_before_hash_evaluation() -> None:
    payload = _fixture()
    payload["admission"]["api_key"] = "must-not-enter-fixture"

    with pytest.raises(GoldenAFixtureError) as failure:
        validate_golden_a_fixture(payload)

    assert failure.value.error_code == "P8_GOLDEN_A_FIXTURE_PRIVATE_DATA"
    assert "api_key" in failure.value.detail


def test_loader_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(GoldenAFixtureError) as failure:
        load_golden_a_fixture(path)

    assert failure.value.error_code == "P8_GOLDEN_A_FIXTURE_UNREADABLE"


@pytest.mark.parametrize(
    ("mutator", "detail"),
    (
        (lambda value: value.update({"unexpected": True}), "top-level fields"),
        (
            lambda value: value.update({"schema_version": "unsupported"}),
            "schema_version is unsupported",
        ),
        (
            lambda value: value.update({"fixture_id": "bad fixture id"}),
            "stable-reference syntax",
        ),
        (
            lambda value: value.update({"tenant": []}),
            "tenant must be an object",
        ),
        (
            lambda value: value["tenant"].update({"unexpected": True}),
            "tenant must contain exactly",
        ),
        (
            lambda value: value.update({"principals": []}),
            "principals must be a non-empty array",
        ),
        (
            lambda value: value.update({"principals": ["not-an-object"]}),
            "principals entries must be objects",
        ),
        (
            lambda value: value["principals"][0].update({"roles": []}),
            "roles must be a non-empty unique string array",
        ),
        (
            lambda value: value["principals"][0].update(
                {"scopes": ["workspace:use", "workspace:use"]}
            ),
            "scopes must be a non-empty unique string array",
        ),
        (
            lambda value: value["principals"][0].update({"display_name": " "}),
            "display_name must be non-empty text",
        ),
        (
            lambda value: value["organization"].update(
                {"effective_from": "2026-01-01T00:00:00"}
            ),
            "must include a timezone",
        ),
        (
            lambda value: value["organization"].update({"effective_from": "bad"}),
            "must be an ISO datetime",
        ),
        (
            lambda value: value["organization"]["units"].append(
                deepcopy(value["organization"]["units"][0])
            ),
            "organization unit ids must be unique",
        ),
        (
            lambda value: value["organization"]["units"][1].update(
                {"parent_org_unit_id": "10000000-0000-4000-8000-000000000099"}
            ),
            "parents must precede",
        ),
        (
            lambda value: value["organization"]["units"][0].update(
                {"org_unit_type": "DIVISION"}
            ),
            "unit type is unsupported",
        ),
        (
            lambda value: value["organization"]["positions"].append(
                deepcopy(value["organization"]["positions"][0])
            ),
            "position ids must be unique",
        ),
        (
            lambda value: value["organization"]["positions"][0].update(
                {"org_unit_id": "10000000-0000-4000-8000-000000000099"}
            ),
            "position must reference",
        ),
        (
            lambda value: value["organization"]["assignments"].append(
                deepcopy(value["organization"]["assignments"][0])
            ),
            "assignment ids must be unique",
        ),
        (
            lambda value: value["organization"]["assignments"][0].update(
                {"position_id": "20000000-0000-4000-8000-000000000099"}
            ),
            "assignment must reference a fixture position",
        ),
        (
            lambda value: value["organization"]["assignments"][0].update(
                {"principal_id": "employee-9999"}
            ),
            "assignment must reference a fixture principal",
        ),
        (
            lambda value: value["projects"]["child"].update(
                {"project_id": value["projects"]["mother"]["project_id"]}
            ),
            "mother and child project ids must differ",
        ),
        (
            lambda value: value["projects"]["mother"].update(
                {"nvt_project_id": "81000000-0000-4000-8000-000000000099"}
            ),
            "mother project must reference",
        ),
        (
            lambda value: value["accounts"].append(deepcopy(value["accounts"][0])),
            "account ids must be unique",
        ),
        (
            lambda value: value["accounts"][0].update({"account_id": "not-a-uuid"}),
            "account_id must be a UUID",
        ),
        (
            lambda value: value["accounts"][0].update({"effective_from": "bad"}),
            "effective_from must be an ISO date",
        ),
        (
            lambda value: value["voucher_line_policy"].update({"policy_version": 2}),
            "policy version or line order",
        ),
        (
            lambda value: value["admission"].update({"operation_semantics": "READ"}),
            "must declare WRITE semantics",
        ),
        (
            lambda value: value["approval_target"].update(
                {"org_unit_id": "10000000-0000-4000-8000-000000000099"}
            ),
            "approval target must reference",
        ),
        (
            lambda value: value["approval_target"].update(
                {"position_type": "TEAM_LEAD"}
            ),
            "matching position assignment",
        ),
        (
            lambda value: value["voucher_line_policy"].update(
                {"effective_from": "2026-10-24"}
            ),
            "policy is not effective",
        ),
        (
            lambda value: value["scenario"].update({"amount": "0"}),
            "positive two-decimal string",
        ),
        (
            lambda value: value["scenario"].update({"attachments": ["object-ref"]}),
            "attachments optional and empty",
        ),
        (
            lambda value: value["tenant"].update({"tenant_id": "another-tenant"}),
            "protected baseline",
        ),
        (
            lambda value: value["organization"].update(
                {"effective_from": "2027-01-01T00:00:00Z"}
            ),
            "protected baseline",
        ),
    ),
)
def test_canonical_validation_rejects_malformed_baseline(mutator, detail) -> None:
    payload = _fixture()
    mutator(payload)
    payload = _rehash(payload)

    with pytest.raises(GoldenAFixtureError, match=detail):
        validate_golden_a_fixture(payload)


def test_nsl_lock_must_be_readable_json(tmp_path: Path) -> None:
    lock_path = tmp_path / "deployment/locks/nsl-v0.2-wheel.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("{", encoding="utf-8")

    with pytest.raises(GoldenAFixtureError, match="NSL lock is unreadable"):
        validate_golden_a_fixture(_fixture(), root=tmp_path)


class _ProjectReadbackFailure:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def list_projects_for_nvt(self, **kwargs):
        return []


class _AccountReadbackFailure:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def get_effective_account(self, **kwargs):
        return None


class _ApproverReadbackMismatch:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def resolve_active_approver_assignment(self, **kwargs):
        result = self._delegate.resolve_active_approver_assignment(**kwargs)
        return {**result, "principal_id": "employee-9999"}


@pytest.mark.parametrize("failure", ("projects", "accounts", "approver"))
def test_seed_fails_when_persisted_readback_differs_from_fixture(failure: str) -> None:
    engine, organization, projects, accounts = _eos_repositories()
    if failure == "projects":
        projects = _ProjectReadbackFailure(projects)
    elif failure == "accounts":
        accounts = _AccountReadbackFailure(accounts)
    else:
        organization = _ApproverReadbackMismatch(organization)
    try:
        with pytest.raises(GoldenAFixtureError) as mismatch:
            seed_golden_a_fixture(
                _fixture(),
                memberships=InMemoryOaTenantMembershipRegistry(),
                organization=organization,
                projects=projects,
                accounts=accounts,
            )
    finally:
        engine.dispose()

    assert mismatch.value.error_code == "P8_GOLDEN_A_SEED_VERIFICATION_FAILED"
