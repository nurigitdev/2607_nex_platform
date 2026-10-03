from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError

from nex_oa.identity_lifecycle_repository import InMemoryOaIdentityLifecycleRepository
from nex_oa.identity_lifecycle_service import (
    OA_IDENTITY_LIFECYCLE_WRITE_SCOPE,
    OaIdentityLifecycleService,
    register_identity_lifecycle_routes,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.subjects import InMemoryOaSubjectRegistry
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
import run_oa_identity_lifecycle_contracts as contracts


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _client() -> TestClient:
    subjects = InMemoryOaSubjectRegistry()
    subjects.ensure_subject({"tenant_id": "tenant-1219", "subject_id": "employee-1219"})
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    memberships.ensure_membership(
        {"tenant_id": "tenant-1219", "subject_id": "employee-1219"}
    )
    repository = InMemoryOaIdentityLifecycleRepository(subjects, memberships)
    service = OaIdentityLifecycleService(subjects, memberships, repository)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_identity_lifecycle_routes(app, service=service)
    return TestClient(app)


def _headers() -> dict[str, str]:
    issued = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, OA_IDENTITY_LIFECYCLE_WRITE_SCOPE],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-1219",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
    }


def test_runtime_subject_response_matches_canonical_schema() -> None:
    response = _client().patch(
        "/internal/v1/identity/tenants/tenant-1219/subjects/employee-1219/lifecycle",
        json={
            "target_status": "DISABLED",
            "expected_revision": 1,
            "reason_code": "admin.deprovision",
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    Draft202012Validator(_load(contracts.SCHEMA_PATHS["subject"])).validate(payload)
    assert contracts._contains_forbidden_key(payload) is False


def test_runtime_membership_response_matches_canonical_schema() -> None:
    response = _client().patch(
        "/internal/v1/identity/tenants/tenant-1219/memberships/employee-1219/lifecycle",
        json={
            "target_status": "DISABLED",
            "expected_revision": 1,
            "reason_code": "admin.membership-disable",
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    Draft202012Validator(_load(contracts.SCHEMA_PATHS["membership"])).validate(
        payload
    )
    assert contracts._contains_forbidden_key(payload) is False


def test_registered_positive_and_negative_fixtures_enforce_privacy() -> None:
    for name in contracts.SCHEMA_PATHS:
        schema = _load(contracts.SCHEMA_PATHS[name])
        positive = _load(contracts.POSITIVE_PATHS[name])
        negative = _load(contracts.NEGATIVE_PATHS[name])
        Draft202012Validator(schema).validate(positive)
        assert contracts._contains_forbidden_key(positive) is False
        assert contracts._contains_forbidden_key(negative) is True
        try:
            Draft202012Validator(schema).validate(negative)
        except ValidationError:
            pass
        else:  # pragma: no cover - explicit contract guard
            raise AssertionError(f"negative fixture validated: {name}")


def test_repository_contract_smoke_passes_with_reduced_known_drift() -> None:
    result = contracts.run_oa_identity_lifecycle_contracts()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["issues"] == []
    assert result["summary"] == {
        "schema_count": 2,
        "positive_fixture_count": 2,
        "negative_fixture_count": 2,
        "documented_operation_count": 2,
        "lifecycle_implemented_count": 8,
        "remaining_lifecycle_gap_count": 0,
        "remaining_contract_drift_count": 23,
        "issue_count": 0,
    }


def test_contract_smoke_fails_closed_without_inputs(tmp_path: Path) -> None:
    result = contracts.run_oa_identity_lifecycle_contracts(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["inputs_present"] is False
    assert result["checks"]["schemas_valid"] is False
    assert result["checks"]["lifecycle_operations_documented"] is False
    assert len(result["issues"]) == 7


def test_contract_helpers_cover_invalid_inputs_and_nested_privacy(tmp_path: Path) -> None:
    issues: list[dict] = []
    invalid_json = tmp_path / "bad.json"
    invalid_json.write_text("{bad", encoding="utf-8")
    assert contracts._load_json(invalid_json, issues, name="bad_json") == {}
    list_json = tmp_path / "list.json"
    list_json.write_text("[]", encoding="utf-8")
    assert contracts._load_json(list_json, issues, name="list_json") == {}

    invalid_yaml = tmp_path / "bad.yaml"
    invalid_yaml.write_text("paths: [", encoding="utf-8")
    assert contracts._load_yaml(invalid_yaml, issues, name="bad_yaml") == {}
    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text("- item\n", encoding="utf-8")
    assert contracts._load_yaml(list_yaml, issues, name="list_yaml") == {}
    assert len(issues) == 4

    assert contracts._schema_valid({"type": "not-a-json-type"}) is False
    assert contracts._schema_valid({}) is False
    assert contracts._payload_valid({}, {}) is False
    assert contracts._payload_rejected({}, {}) is False
    assert contracts._contains_forbidden_key([{"password_hash": "private"}]) is True
    assert contracts._contains_forbidden_key("safe") is False
    assert contracts._mapping(None) == {}


def test_safe_audit_summary_and_main_paths(monkeypatch, capsys) -> None:
    assert contracts._safe_audit(
        lambda _root: (_ for _ in ()).throw(RuntimeError("private")), ROOT
    ) == {"status": "FAIL", "failure_code": "RuntimeError"}
    assert contracts._safe_audit(lambda _root: None, ROOT) == {"status": "FAIL"}

    passing = contracts.run_oa_identity_lifecycle_contracts()
    assert "contracts=pass" in contracts.summary_line(passing)
    assert "contract_drift=23" in contracts.summary_line(passing)
    monkeypatch.setattr(
        contracts,
        "run_oa_identity_lifecycle_contracts",
        lambda: passing,
    )
    assert contracts.main(["--summary"]) == 0
    assert "operations=2" in capsys.readouterr().out
    assert contracts.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        contracts,
        "run_oa_identity_lifecycle_contracts",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert contracts.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
