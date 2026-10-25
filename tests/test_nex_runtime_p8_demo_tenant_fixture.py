from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from nex_runtime.demo_database import DemoDatabaseGuardError
from nex_runtime.demo_tenant import (
    _tenant_predicate,
    _tenant_tables,
    build_tenant_delete_order,
    inspect_demo_tenant_database,
    reset_demo_tenant_database,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, *, rows=(), scalar=None, rowcount=0):
        self._rows = list(rows)
        self._scalar = scalar
        self.rowcount = rowcount

    def all(self):
        return list(self._rows)

    def one(self):
        return self._rows[0]

    def scalar_one(self):
        return self._scalar


class _Connection:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        query = " ".join(str(statement).split())
        if query == "SELECT current_database(), current_user":
            return _Result(rows=[self.engine.identity])
        if "information_schema.columns" in query:
            return _Result(
                rows=[
                    (table, column)
                    for table, values in self.engine.tables.items()
                    for column in values["columns"]
                ]
            )
        if "FROM pg_constraint" in query:
            return _Result(rows=self.engine.foreign_keys)
        if query.startswith("SELECT count(*) FROM"):
            table = query.split('"')[1]
            return _Result(scalar=self.engine.tables[table]["count"])
        if query.startswith("DELETE FROM"):
            table = query.split('"')[1]
            before = self.engine.tables[table]["count"]
            self.engine.tables[table]["count"] = 0
            return _Result(rowcount=before)
        raise AssertionError(query)


class _Engine:
    def __init__(self, *, identity=("nex_ae_dev", "nex_ae_user")):
        self.identity = identity
        self.tables = {
            "ae_parent": {"columns": ("tenant_id",), "count": 1},
            "ae_child": {"columns": ("tenant_id",), "count": 2},
            "ae_dual": {
                "columns": ("tenant_id", "tenant_ref_id"),
                "count": 3,
            },
        }
        self.foreign_keys = (("ae_child", "ae_parent"),)

    def connect(self):
        return _Connection(self)

    def begin(self):
        return _Connection(self)


def test_tenant_delete_order_is_child_first_deterministic_and_rejects_cycle() -> None:
    assert build_tenant_delete_order(
        ("parent", "child", "independent"),
        (("child", "parent"), ("child", "parent"), ("child", "child")),
    ) == ("child", "independent", "parent")
    with pytest.raises(DemoDatabaseGuardError, match="foreign_key_cycle"):
        build_tenant_delete_order(("a", "b"), (("a", "b"), ("b", "a")))
    with pytest.raises(DemoDatabaseGuardError, match="identifier_invalid"):
        build_tenant_delete_order(("bad-name",), ())


def test_tenant_inspection_and_reset_are_identity_bound_and_tenant_only() -> None:
    engine = _Engine()
    inspected = inspect_demo_tenant_database(
        engine,
        service_id="nex-ae-api",
        expected_database_name="nex_ae_dev",
        expected_role_name="nex_ae_user",
    )
    assert inspected["tenant_table_count"] == 3
    assert inspected["row_count"] == 6
    assert inspected["inventory_hash"].startswith("sha256:")

    reset = reset_demo_tenant_database(
        engine,
        service_id="nex-ae-api",
        expected_database_name="nex_ae_dev",
        expected_role_name="nex_ae_user",
    )
    assert reset["delete_order"] == ["ae_child", "ae_dual", "ae_parent"]
    assert reset["rows_deleted"] == 6
    assert reset["rows_after"] == 0
    assert reset["mutation_scope"] == "TENANT_ONLY"

    with pytest.raises(DemoDatabaseGuardError, match="reset_scope_invalid"):
        reset_demo_tenant_database(
            engine,
            service_id="nex-ae-api",
            expected_database_name="nex_ae_dev",
            expected_role_name="nex_ae_user",
            tenant_id="other",
        )


def test_tenant_inspection_rejects_wrong_identity() -> None:
    with pytest.raises(DemoDatabaseGuardError, match="identity_mismatch"):
        inspect_demo_tenant_database(
            _Engine(identity=("wrong", "nex_ae_user")),
            service_id="nex-ae-api",
            expected_database_name="nex_ae_dev",
            expected_role_name="nex_ae_user",
        )


def test_tenant_helpers_reject_invalid_columns_empty_predicate_and_residue() -> None:
    with pytest.raises(DemoDatabaseGuardError, match="columns_empty"):
        _tenant_predicate(())

    class InvalidColumnConnection:
        def execute(self, _statement):
            return _Result(rows=[("valid_table", "other")])

    with pytest.raises(DemoDatabaseGuardError, match="column_invalid"):
        _tenant_tables(InvalidColumnConnection())

    class ResidueConnection(_Connection):
        def execute(self, statement, params=None):
            query = " ".join(str(statement).split())
            if query.startswith("DELETE FROM"):
                table = query.split('"')[1]
                return _Result(rowcount=self.engine.tables[table]["count"])
            return super().execute(statement, params)

    class ResidueEngine(_Engine):
        def begin(self):
            return ResidueConnection(self)

    with pytest.raises(DemoDatabaseGuardError, match="residue_detected"):
        reset_demo_tenant_database(
            ResidueEngine(),
            service_id="nex-ae-api",
            expected_database_name="nex_ae_dev",
            expected_role_name="nex_ae_user",
        )

def _load_script():
    path = ROOT / "scripts/deployment/run_p8_demo_tenant_fixture.py"
    spec = importlib.util.spec_from_file_location("p8_demo_tenant_fixture", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vo00_fixture_loads_from_hash_bound_base_and_has_no_password() -> None:
    module = _load_script()
    document, business = module.load_demo_fixture()
    assert document["tenant"]["tenant_id"] == "VO00"
    assert business["tenant"]["tenant_id"] == "VO00"
    assert business["fixture_hash"].startswith("sha256:")
    serialized = json.dumps(document)
    assert "password_env" in serialized
    assert '"password"' not in serialized


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda payload: payload.update(schema_version="bad"), "schema_invalid"),
        (
            lambda payload: payload["tenant"].update(tenant_id="other"),
            "tenant_invalid",
        ),
        (
            lambda payload: payload["base_fixture"].update(fixture_hash="sha256:" + "f" * 64),
            "base_hash_mismatch",
        ),
    ),
)
def test_vo00_fixture_rejects_tamper(tmp_path: Path, mutation, code: str) -> None:
    module = _load_script()
    payload = json.loads(module.DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    mutation(payload)
    hash_input = dict(payload)
    hash_input.pop("fixture_hash")
    payload["fixture_hash"] = semantic_sha256_hash_ref(hash_input)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DemoDatabaseGuardError, match=code):
        module.load_demo_fixture(path)


def test_fixture_expected_state_accepts_only_exact_owner_rows() -> None:
    module = _load_script()
    document, business = module.load_demo_fixture()
    expected = [
        {
            "service_id": "nex-oa",
            "table_counts": {
                "oa_tenants": 1,
                "oa_subjects": 2,
                "oa_tenant_memberships": 2,
                "oa_local_credentials": 2,
                "oa_auth_events": 0,
            },
        },
        {
            "service_id": "nex-eos",
            "table_counts": {
                "eos_nvt_project": 1,
                "eos_project": 2,
                "eos_project_member": 2,
                "eos_account": 2,
                "eos_org_unit": 4,
                "eos_position": 1,
                "eos_position_assignment": 1,
            },
        },
        {"service_id": "nex-cx", "table_counts": {"cx_content_objects": 0}},
    ]
    module._require_expected_state(expected, document)
    expected[1]["table_counts"]["eos_project"] = 3
    with pytest.raises(DemoDatabaseGuardError, match="existing_state_conflict"):
        module._require_expected_state(expected, document)

    broken = json.loads(json.dumps(document))
    broken["login_accounts"][0]["subject_id"] = "unknown"
    with pytest.raises(DemoDatabaseGuardError, match="login_accounts_invalid"):
        module._validate_accounts_and_memberships(broken, business)


def test_fixture_summary_does_not_require_secret_fields() -> None:
    module = _load_script()
    report = {
        "status": "PASS",
        "action": "SEED",
        "execution_state": "SEEDED",
        "tenant_id": "VO00",
        "service_count": 7,
        "operations": [{"row_count": 17}],
    }
    assert "tenant=VO00" in module.summary_line(report)
