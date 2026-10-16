from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import nex_ae_api.skill_artifacts as artifact_module
import pytest
from nex_ae_api.skill_artifacts import (
    SkillArtifactGateway,
    SkillArtifactGatewayError,
    SqlAlchemySkillArtifactRepository,
    skill_artifact_table_sql,
    validate_verified_skill_artifact,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2201_ae_nsl_artifact.sql"
SCHEMA = ROOT / "docs/transition/P6/contracts/p6-verified-skill-artifact-v1.schema.json"
GOLDEN = ROOT / "docs/transition/P6/contracts/examples/p6-golden-verified-artifact-v1.json"
NOW = "2026-10-14T07:01:00Z"


class FakeResolver:
    def __init__(self, resolved: object | None = None, error: Exception | None = None):
        self.resolved = resolved or _resolved()
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def resolve(self, *, skill_id: str, skill_version: str) -> object:
        self.calls.append((skill_id, skill_version))
        if self.error is not None:
            raise self.error
        return self.resolved


class FakeAdmissionSource:
    def __init__(
        self,
        record: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.record = _admission_record() if record is None else record
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def current_admission(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.record)


@pytest.fixture
def artifact_store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        for statement in skill_artifact_table_sql("sqlite"):
            connection.execute(text(statement))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield engine, SqlAlchemySkillArtifactRepository(factory)
    engine.dispose()


def _golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _resolved(
    *,
    skill_id: str = "FINANCE.PROJECT_BUDGET_CHECK",
    skill_version: str = "1.0.0",
    semantic_hash: str | None = None,
    package_hash: str | None = None,
    signing_key_id: str | None = "publisher.p6-golden-1",
) -> object:
    golden = _golden()
    return SimpleNamespace(
        skill=SimpleNamespace(
            skill_id=skill_id,
            skill_version=skill_version,
            semantic_hash=semantic_hash or golden["skill_semantic_hash"],
        ),
        package_hash=package_hash or golden["package_hash"],
        signer_key_id=signing_key_id,
    )


def _admission_record() -> dict[str, Any]:
    golden = _golden()
    trust = {
        "evidence_ref": golden["trust_evidence"]["evidence_ref"],
        "package_id": golden["package_id"],
        "package_hash": golden["package_hash"],
        "publisher_id": golden["publisher_id"],
        "signing_key_id": golden["signing_key_id"],
        "verified_at": golden["trust_evidence"]["verified_at"],
        "trust_policy_id": golden["trust_evidence"]["trust_policy_id"],
        "trust_status": "VALID",
        "governance_status": "ACTIVE",
        "governance_decision_ref": golden["trust_evidence"][
            "governance_decision_ref"
        ],
        "evidence_hash": golden["trust_evidence"]["evidence_hash"],
    }
    admission = {
        "decision_id": golden["artifact_admission_decision_ref"],
        "decision": "ADMITTED",
        "package_id": golden["package_id"],
        "package_hash": golden["package_hash"],
        "publisher_id": golden["publisher_id"],
        "signing_key_id": golden["signing_key_id"],
        "governance_status": "ACTIVE",
        "trust_policy_id": golden["trust_evidence"]["trust_policy_id"],
        "package_trust_evidence_ref": golden["trust_evidence"]["evidence_ref"],
        "reason_codes": [],
        "decided_at": golden["trust_evidence"]["verified_at"],
    }
    return {
        "trust_evidence": trust,
        "admission_decision": admission,
        "admission_decision_hash": golden["artifact_admission_decision_hash"],
    }


def _gateway(
    repository: SqlAlchemySkillArtifactRepository,
    *,
    resolver: FakeResolver | None = None,
    admission: FakeAdmissionSource | None = None,
) -> tuple[SkillArtifactGateway, FakeResolver, FakeAdmissionSource]:
    exact_resolver = resolver or FakeResolver()
    source = admission or FakeAdmissionSource()
    return (
        SkillArtifactGateway(
            resolver=exact_resolver,
            admission_source=source,
            repository=repository,
        ),
        exact_resolver,
        source,
    )


def _resolve(gateway: SkillArtifactGateway, **overrides: Any) -> dict[str, Any]:
    golden = _golden()
    arguments = {
        "tenant_id": "tenant-p6-s2",
        "skill_id": golden["skill_id"],
        "exact_version": golden["skill_version"],
        "expected_semantic_hash": golden["skill_semantic_hash"],
        "runtime_contract_ref": golden["runtime_contract_ref"],
        "trust_policy_id": golden["trust_evidence"]["trust_policy_id"],
        "environment": "production",
        "observed_at": NOW,
    }
    arguments.update(overrides)
    return gateway.resolve_verified(**arguments)


def test_migration_contract_is_bounded_and_uses_short_names() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "2201_ae_nsl_artifact" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_nsl_artifact" in sql
    assert "artifact_json JSONB" in sql
    assert "signature" not in sql.lower()
    assert "package_bytes" not in sql.lower()
    assert all(
        len(name) <= 30
        for name in (
            "ae_nsl_artifact",
            "ux_ae_nsl_artifact_hash",
            "ck_ae_nsl_artifact_json",
            "idx_ae_nsl_artifact_skill",
        )
    )


def test_gateway_resolves_exact_verified_artifact_and_persists_idempotently(
    artifact_store,
) -> None:
    _, repository = artifact_store
    gateway, resolver, source = _gateway(repository)

    first = _resolve(gateway)
    second = _resolve(gateway)

    assert first == second
    assert resolver.calls == [
        ("FINANCE.PROJECT_BUDGET_CHECK", "1.0.0"),
        ("FINANCE.PROJECT_BUDGET_CHECK", "1.0.0"),
    ]
    assert source.calls[0]["tenant_id"] == "tenant-p6-s2"
    assert first["package_id"].startswith("nsp:")
    assert first["backend_artifact_handle"].startswith("nsp+sha256://")
    assert first["artifact_admission_decision_hash"] == _golden()[
        "artifact_admission_decision_hash"
    ]
    assert first["trust_evidence"] == _golden()["trust_evidence"]
    assert first["artifact_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in first.items() if key != "artifact_hash"}
    )
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text())).validate(first)
    assert repository.get(
        tenant_id="tenant-p6-s2", artifact_ref=first["artifact_ref"]
    ) == first
    assert repository.get_by_hash(
        tenant_id="tenant-p6-s2", artifact_hash=first["artifact_hash"]
    ) == first
    assert repository.get(
        tenant_id="another-tenant", artifact_ref=first["artifact_ref"]
    ) is None
    assert repository.get_by_hash(
        tenant_id="another-tenant", artifact_hash=first["artifact_hash"]
    ) is None
    assert not any(
        forbidden in json.dumps(first).lower()
        for forbidden in ("signature_bytes", "package_bytes", "verification_journal")
    )


def test_gateway_rejects_resolution_mismatch_before_governance_lookup(
    artifact_store,
) -> None:
    _, repository = artifact_store
    cases = (
        (_resolved(skill_id="OTHER.SKILL"), "ae.skill_artifact_trust_rejected"),
        (
            _resolved(semantic_hash="sha256:" + "a" * 64),
            "ae.skill_artifact_semantic_mismatch",
        ),
        (_resolved(signing_key_id=None), "ae.skill_artifact_trust_rejected"),
        (SimpleNamespace(skill=None), "ae.skill_artifact_trust_rejected"),
    )
    for resolved, error_code in cases:
        admission = FakeAdmissionSource()
        gateway, _, _ = _gateway(
            repository, resolver=FakeResolver(resolved=resolved), admission=admission
        )
        with pytest.raises(SkillArtifactGatewayError) as caught:
            _resolve(gateway)
        assert caught.value.error_code == error_code
        assert admission.calls == []

    gateway, _, source = _gateway(
        repository, resolver=FakeResolver(error=RuntimeError("raw secret"))
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value.error_code == "ae.skill_artifact_resolution_failed"
    assert "secret" not in caught.value.detail
    assert source.calls == []


@pytest.mark.parametrize(
    ("mutation", "expected_code", "retryable"),
    (
        (lambda record: None, "ae.skill_artifact_trust_rejected", False),
        (
            lambda record: record["trust_evidence"].update(
                {"trust_status": "REVOKED"}
            )
            or record,
            "ae.skill_artifact_trust_rejected",
            False,
        ),
        (
            lambda record: record["admission_decision"].update(
                {"decision": "REJECTED", "governance_status": "REVOKED"}
            )
            or record,
            "ae.skill_artifact_trust_rejected",
            False,
        ),
        (
            lambda record: record["trust_evidence"].update(
                {"verified_at": "2026-10-15T07:00:00Z"}
            )
            or record,
            "ae.skill_artifact_trust_rejected",
            False,
        ),
        (
            lambda record: record.update(
                {"admission_decision_hash": "sha256:" + "0" * 64}
            )
            or record,
            "ae.skill_artifact_trust_rejected",
            False,
        ),
    ),
)
def test_gateway_fails_closed_for_noncurrent_trust(
    artifact_store, mutation, expected_code: str, retryable: bool
) -> None:
    _, repository = artifact_store
    record = mutation(_admission_record())
    source = FakeAdmissionSource(record={})
    source.record = record
    gateway, _, _ = _gateway(repository, admission=source)
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value.error_code == expected_code
    assert caught.value.retryable is retryable


def test_gateway_marks_admission_source_and_repository_outage_retryable(
    artifact_store,
) -> None:
    engine, repository = artifact_store
    gateway, _, _ = _gateway(
        repository, admission=FakeAdmissionSource(error=OSError("endpoint token"))
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value.error_code == "ae.skill_artifact_trust_unavailable"
    assert caught.value.retryable is True
    assert "token" not in caught.value.detail

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_nsl_artifact"))
    gateway, _, _ = _gateway(repository)
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value.error_code == "ae.skill_artifact_persistence_unavailable"
    assert caught.value.retryable is True


def test_gateway_preserves_bounded_domain_errors_and_wraps_unknown_store_errors(
    artifact_store,
) -> None:
    _, repository = artifact_store
    domain_error = SkillArtifactGatewayError("bounded.code", "bounded detail")
    gateway, _, _ = _gateway(
        repository, resolver=FakeResolver(error=domain_error)
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value is domain_error
    assert str(caught.value) == "bounded detail"

    gateway, _, _ = _gateway(
        repository, admission=FakeAdmissionSource(error=domain_error)
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value is domain_error

    class BrokenRepository:
        def save(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("database password")

    gateway = SkillArtifactGateway(
        resolver=FakeResolver(),
        admission_source=FakeAdmissionSource(),
        repository=BrokenRepository(),
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway, observed_at=None)
    assert caught.value.error_code == "ae.skill_artifact_persistence_unavailable"
    assert caught.value.retryable is True
    assert "password" not in caught.value.detail


@pytest.mark.parametrize(
    "mutation",
    (
        lambda record: [record],
        lambda record: {"trust_evidence": record["trust_evidence"]},
        lambda record: record["trust_evidence"].update({"unexpected": True})
        or record,
        lambda record: record["trust_evidence"].update(
            {"evidence_hash": "sha256:" + "0" * 64}
        )
        or record,
        lambda record: record["admission_decision"].update({"unexpected": True})
        or record,
        lambda record: record["admission_decision"].update(
            {"reason_codes": [""]}
        )
        or record,
        lambda record: record["admission_decision"].update(
            {"decided_at": "2026-10-15T07:00:00Z"}
        )
        or record,
    ),
)
def test_gateway_rejects_malformed_governance_records(
    artifact_store, mutation
) -> None:
    _, repository = artifact_store
    record = mutation(_admission_record())
    source = FakeAdmissionSource(record={})
    source.record = record
    gateway, _, _ = _gateway(repository, admission=source)
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(gateway)
    assert caught.value.error_code == "ae.skill_artifact_trust_rejected"


def test_artifact_validation_rejects_tampering_and_bad_inputs(artifact_store) -> None:
    _, repository = artifact_store
    gateway, _, _ = _gateway(repository)
    artifact = _resolve(gateway)

    mutations = []
    wrong_hash = copy.deepcopy(artifact)
    wrong_hash["artifact_hash"] = "sha256:" + "0" * 64
    mutations.append(wrong_hash)
    wrong_package = copy.deepcopy(artifact)
    wrong_package["package_id"] = "nsp:" + "0" * 64
    mutations.append(wrong_package)
    wrong_trust = copy.deepcopy(artifact)
    wrong_trust["trust_evidence"]["governance_status"] = "REVOKED"
    mutations.append(wrong_trust)
    extra = copy.deepcopy(artifact)
    extra["raw_package"] = "forbidden"
    mutations.append(extra)
    nonmapping_trust = copy.deepcopy(artifact)
    nonmapping_trust["trust_evidence"] = []
    mutations.append(nonmapping_trust)
    extra_trust = copy.deepcopy(artifact)
    extra_trust["trust_evidence"]["extra"] = True
    mutations.append(extra_trust)
    wrong_evidence_hash = copy.deepcopy(artifact)
    wrong_evidence_hash["trust_evidence"]["evidence_hash"] = "sha256:" + "0" * 64
    mutations.append(wrong_evidence_hash)

    for value in mutations:
        with pytest.raises(SkillArtifactGatewayError) as caught:
            validate_verified_skill_artifact(value)
        assert caught.value.error_code == "ae.skill_artifact_invalid"

    for overrides in (
        {"skill_id": "contains space"},
        {"expected_semantic_hash": "not-a-hash"},
        {"environment": "unknown"},
        {"observed_at": "2026-10-14T07:00:00"},
        {"observed_at": "not-a-timestamp"},
        {"observed_at": 7},
        {"tenant_id": ""},
    ):
        with pytest.raises(SkillArtifactGatewayError) as caught:
            _resolve(gateway, **overrides)
        assert caught.value.error_code == "ae.skill_artifact_invalid"

    with pytest.raises(SkillArtifactGatewayError):
        validate_verified_skill_artifact({"not_json": {1, 2}})

    development_gateway, _, _ = _gateway(
        repository, resolver=FakeResolver(resolved=_resolved(signing_key_id=None))
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        _resolve(development_gateway, environment="development")
    assert "contract requires a signing key" in caught.value.detail


def test_repository_detects_immutable_conflict(artifact_store) -> None:
    engine, repository = artifact_store
    gateway, _, _ = _gateway(repository)
    artifact = _resolve(gateway)
    changed = copy.deepcopy(artifact)
    changed["runtime_contract_ref"] = "contract://nex/nsl/read-runtime/changed"
    changed["artifact_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed.items() if key != "artifact_hash"}
    )
    with pytest.raises(SkillArtifactGatewayError) as caught:
        repository.save(tenant_id="tenant-p6-s2", artifact=changed)
    assert caught.value.error_code == "ae.skill_artifact_immutable_conflict"

    with engine.begin() as connection:
        count = connection.execute(text("SELECT count(*) FROM ae_nsl_artifact")).scalar()
    assert count == 1


def test_repository_read_failures_and_persisted_json_guard(artifact_store) -> None:
    engine, repository = artifact_store
    gateway, _, _ = _gateway(repository)
    artifact = _resolve(gateway)

    with pytest.raises(SkillArtifactGatewayError):
        artifact_module._artifact_json([])
    assert "JSONB" in artifact_module.skill_artifact_table_sql("postgresql")[0]
    assert "CAST(:artifact_json AS JSONB)" in artifact_module._insert_sql("postgresql")

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_nsl_artifact"))
    with pytest.raises(SkillArtifactGatewayError) as caught:
        repository.get(
            tenant_id="tenant-p6-s2", artifact_ref=artifact["artifact_ref"]
        )
    assert caught.value.error_code == "ae.skill_artifact_persistence_unavailable"
    with pytest.raises(SkillArtifactGatewayError) as caught:
        repository.get_by_hash(
            tenant_id="tenant-p6-s2", artifact_hash=artifact["artifact_hash"]
        )
    assert caught.value.retryable is True
