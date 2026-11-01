from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nex_eos import project_operations as projects
from nex_eos.project_operations import EosGovernedProjectError
from nex_oa import subjects
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry, SubjectRegistryError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class _Session:
    def __init__(self, *, dialect="postgresql"):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    def get_bind(self):
        return self.bind


class _FailingFactory:
    def __call__(self):
        raise SQLAlchemyError("database unavailable")


def _tenant_payload():
    return {"tenant_id": "VO00", "tenant_display_name": "VO00"}


def _subject_payload():
    return {
        "tenant_id": "VO00",
        "subject_id": "E0001",
        "subject_display_name": "Employee",
        "metadata": {"department": "FINANCE"},
    }


def _integrity_error():
    return IntegrityError("insert", {}, RuntimeError("duplicate"))


def test_oa_sql_registry_integrity_replay_and_unavailable(monkeypatch):
    registry = SqlAlchemyOaSubjectRegistry(lambda: _Session())
    tenant = subjects.build_tenant_record(_tenant_payload())
    snapshot = subjects.build_subject_registry_snapshot(
        tenant=tenant,
        subject=subjects.build_subject_record(_subject_payload(), tenant=tenant),
    )
    monkeypatch.setattr(
        registry, "_run_in_transaction", lambda _operation: (_ for _ in ()).throw(_integrity_error())
    )
    monkeypatch.setattr(registry, "get_tenant", lambda _tenant_id: tenant)
    assert registry.ensure_tenant(_tenant_payload()) == tenant
    monkeypatch.setattr(registry, "get_subject", lambda **_kwargs: snapshot)
    assert registry.ensure_subject(_subject_payload()) == snapshot

    monkeypatch.setattr(registry, "get_tenant", lambda _tenant_id: None)
    with pytest.raises(SubjectRegistryError) as tenant_conflict:
        registry.ensure_tenant(_tenant_payload())
    assert tenant_conflict.value.retryable is True
    monkeypatch.setattr(registry, "get_subject", lambda **_kwargs: None)
    with pytest.raises(SubjectRegistryError) as subject_conflict:
        registry.ensure_subject(_subject_payload())
    assert subject_conflict.value.retryable is True

    unavailable = SqlAlchemyOaSubjectRegistry(_FailingFactory())
    for operation in (
        lambda: unavailable.ensure_tenant(_tenant_payload()),
        lambda: unavailable.ensure_subject(_subject_payload()),
        lambda: unavailable.get_tenant("VO00"),
        lambda: unavailable.get_subject(tenant_id="VO00", subject_id="E0001"),
    ):
        with pytest.raises(SubjectRegistryError) as caught:
            operation()
        assert caught.value.error_code == "oa.subject_registry_unavailable"


def test_oa_subject_metadata_and_json_datetime_boundaries():
    assert subjects._metadata_from_payload(None) == {}
    with pytest.raises(SubjectRegistryError):
        subjects._metadata_from_payload([])
    with pytest.raises(SubjectRegistryError):
        subjects._metadata_from_payload({"bad": {1}})
    with pytest.raises(SubjectRegistryError):
        subjects._non_empty_text(1, field_name="subject_id")

    assert subjects._json_sql_expression(_Session(), "metadata") == "CAST(:metadata AS JSONB)"
    assert subjects._json_sql_expression(_Session(dialect="sqlite"), "metadata") == ":metadata"
    assert subjects._json_loads(None, default={}) == {}
    assert subjects._json_loads({"safe": True}, default={}) == {"safe": True}
    assert subjects._json_loads(b'{"safe":true}', default={}) == {"safe": True}
    assert subjects._json_loads(42, default={}) == {}
    naive = datetime(2026, 11, 1, 3, 0)  # noqa: DTZ001 - exercises legacy naive timestamps
    assert subjects._timestamp_to_wire(naive) == "2026-11-01T03:00:00Z"
    aware = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    assert subjects._timestamp_to_wire(aware) == "2026-11-01T03:00:00Z"


@pytest.mark.parametrize(
    "operation",
    (
        lambda: projects.project_operation_payload_hash({}, "UNKNOWN.OPERATION"),
        lambda: projects.project_membership_add_many_payload_hash([]),
        lambda: projects._write_envelope([], projects.NVT_PROJECT_CREATE_OPERATION),
        lambda: projects._write_envelope(
            {"requested_operation": "UNKNOWN.OPERATION"},
            projects.NVT_PROJECT_CREATE_OPERATION,
        ),
        lambda: projects._batch_write_envelope([]),
        lambda: projects._batch_write_envelope({"requested_operation": "UNKNOWN.OPERATION"}),
        lambda: projects._canonical_subject_ids("E0001"),
        lambda: projects._object("project", []),
    ),
)
def test_eos_project_contract_rejects_malformed_operation_inputs(operation):
    with pytest.raises(EosGovernedProjectError):
        operation()


def test_eos_project_operation_route_and_batch_name_mismatch():
    with pytest.raises(EosGovernedProjectError, match="does not match"):
        projects._write_envelope(
            {"requested_operation": projects.PROJECT_DEACTIVATE_OPERATION},
            projects.NVT_PROJECT_CREATE_OPERATION,
        )
    with pytest.raises(EosGovernedProjectError, match="does not match"):
        projects._batch_write_envelope(
            {"requested_operation": projects.NVT_PROJECT_CREATE_OPERATION}
        )


def test_eos_project_batch_and_authorization_denials():
    with pytest.raises(EosGovernedProjectError):
        projects._canonical_subject_ids([])
    with pytest.raises(EosGovernedProjectError):
        projects._canonical_subject_ids(["E0002", "E0001"])
    with pytest.raises(EosGovernedProjectError):
        projects._canonical_subject_ids(["E0001", "E0001"])
    with pytest.raises(EosGovernedProjectError):
        projects._hash_ref("evidence", "bad")
    with pytest.raises(EosGovernedProjectError):
        projects._batch_member_role("UNKNOWN")

    counts = projects._batch_outcome_counts(
        [
            {"outcome": "ADDED"},
            {"outcome": "REACTIVATED"},
            {"outcome": "SUBJECT_INACTIVE"},
        ]
    )
    assert projects._batch_operation_status(counts) == "PARTIALLY_APPLIED"
    assert projects._batch_operation_status({**counts, "rejected_count": 0}) == "APPLIED"
    assert projects._batch_operation_status(
        {"added_count": 0, "reactivated_count": 0, "rejected_count": 1}
    ) == "REJECTED"
    assert projects._batch_operation_status(
        {"added_count": 0, "reactivated_count": 0, "rejected_count": 0}
    ) == "NO_CHANGE"

    base = {
        "active": True,
        "tenant_id": "VO00",
        "subject_id": "E0001",
        "scopes": ["project:read"],
        "revision_hash": "a" * 64,
    }
    assert projects._admit_authorization(
        base, tenant_id="VO00", subject_id="E0001", required_scope="project:read"
    )["revision_hash"] == base["revision_hash"]
    for value in (
        None,
        {**base, "active": False},
        {**base, "tenant_id": "OTHER"},
        {**base, "scopes": []},
        {**base, "revision_hash": "bad"},
        {**base, "project_ids": ["other"]},
    ):
        with pytest.raises(EosGovernedProjectError):
            projects._admit_authorization(
                value,
                tenant_id="VO00",
                subject_id="E0001",
                required_scope="project:read",
                project_id="project-1",
            )


def test_eos_project_error_mapping():
    source = projects.EosProjectError("EOS_SOURCE", "source detail", status_code=409)
    mapped = projects._governed_project_error(source)
    assert mapped.error_code == "EOS_SOURCE"
    assert mapped.status_code == 409
