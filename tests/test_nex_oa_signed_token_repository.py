from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import nex_oa.signed_token_repository as repository_module
import pytest
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.signed_token_repository import (
    InMemoryOaSignedTokenRepository,
    SqlAlchemyOaSignedTokenRepository,
    build_signed_token_repository_for_runtime,
)
from nex_oa.signed_tokens import (
    OaSignedTokenError,
    build_signing_key_record,
    build_test_public_jwk,
    build_token_revocation_record,
    plan_signing_key_transition,
)
from nex_runtime import (
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    build_service_persistence_runtime,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _key(key_id: str) -> dict:
    return build_signing_key_record(
        {
            "key_id": key_id,
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": build_test_public_jwk(key_id),
            "private_key_ref": "file:///tmp/key.pem",
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 800,
            "verify_until": 1_130,
        },
        deployment_profile="test",
    )


def _revocation(revocation_id: str = "rev-one", jti: str = "jti-one") -> dict:
    return build_token_revocation_record(
        {
            "iss": PRODUCTION_TOKEN_ISSUER,
            "sub": "service:nex-ae-api",
            "aud": "nex-cx",
            "jti": jti,
            "token_use": "service_access",
            "exp": 900,
        },
        reason_code="OPERATOR",
        now_epoch=600,
        revocation_id=revocation_id,
    )


@pytest.fixture(params=("memory", "sqlite"))
def repository(request):
    if request.param == "memory":
        yield InMemoryOaSignedTokenRepository()
        return
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        for statement in _SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    yield SqlAlchemyOaSignedTokenRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    engine.dispose()


def test_repository_persists_keys_transitions_and_restart_reads(repository) -> None:
    first = repository.save_signing_key(_key("oa-key-a"))
    active = plan_signing_key_transition(
        first, target_state="ACTIVE", expected_revision=1, now_epoch=430
    )
    repository.save_signing_key(active)

    assert repository.get_signing_key("oa-key-a")["state"] == "ACTIVE"
    assert repository.list_signing_keys()[0]["public_jwk"]["kid"] == "oa-key-a"


def test_repository_enforces_revision_and_one_active_key(repository) -> None:
    first = repository.save_signing_key(_key("oa-key-a"))
    second = repository.save_signing_key(_key("oa-key-b"))
    repository.save_signing_key(
        plan_signing_key_transition(
            first, target_state="ACTIVE", expected_revision=1, now_epoch=430
        )
    )
    with pytest.raises(OaSignedTokenError, match="active signing key"):
        repository.save_signing_key(
            plan_signing_key_transition(
                second, target_state="ACTIVE", expected_revision=1, now_epoch=430
            )
        )
    with pytest.raises(OaSignedTokenError, match="revision conflict"):
        repository.save_signing_key({**first, "revision": 2, "previous_revision": 1})


def test_repository_rotates_signing_keys_atomically(repository) -> None:
    first = repository.save_signing_key(_key("oa-key-a"))
    second = repository.save_signing_key(_key("oa-key-b"))
    active_first = plan_signing_key_transition(
        first, target_state="ACTIVE", expected_revision=1, now_epoch=430
    )
    repository.save_signing_key(active_first)
    previous = plan_signing_key_transition(
        active_first,
        target_state="VERIFY_ONLY",
        expected_revision=2,
        now_epoch=500,
    )
    active = plan_signing_key_transition(
        second,
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )

    stored_previous, stored_active = repository.rotate_signing_keys(
        previous, active
    )

    assert stored_previous["state"] == "VERIFY_ONLY"
    assert stored_active["state"] == "ACTIVE"
    assert repository.get_signing_key("oa-key-a")["state"] == "VERIFY_ONLY"
    assert repository.get_signing_key("oa-key-b")["state"] == "ACTIVE"


def test_repository_rotation_failure_rolls_back_both_keys(repository) -> None:
    first = repository.save_signing_key(_key("oa-key-a"))
    second = repository.save_signing_key(_key("oa-key-b"))
    active_first = plan_signing_key_transition(
        first, target_state="ACTIVE", expected_revision=1, now_epoch=430
    )
    repository.save_signing_key(active_first)
    previous = plan_signing_key_transition(
        active_first,
        target_state="VERIFY_ONLY",
        expected_revision=2,
        now_epoch=500,
    )
    active = plan_signing_key_transition(
        second,
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )

    with pytest.raises(OaSignedTokenError, match="revision conflict"):
        repository.rotate_signing_keys(
            previous,
            {**active, "previous_revision": 99},
        )

    assert repository.get_signing_key("oa-key-a")["state"] == "ACTIVE"
    assert repository.get_signing_key("oa-key-b")["state"] == "PREPUBLISHED"


def test_repository_rotation_rejects_same_key(repository) -> None:
    first = repository.save_signing_key(_key("oa-key-a"))
    with pytest.raises(OaSignedTokenError, match="revision conflict"):
        repository.rotate_signing_keys(first, first)


def test_memory_rotation_rejects_missing_invalid_and_competing_keys() -> None:
    repository = InMemoryOaSignedTokenRepository()
    first = repository.save_signing_key(_key("oa-key-a"))
    second = repository.save_signing_key(_key("oa-key-b"))
    with pytest.raises(OaSignedTokenError, match="revision conflict"):
        repository.rotate_signing_keys(first, _key("oa-key-missing"))

    invalid_previous = {
        **first,
        "state": "ACTIVE",
        "revision": 2,
        "previous_revision": 1,
    }
    planned_active = {
        **second,
        "state": "ACTIVE",
        "revision": 2,
        "previous_revision": 1,
    }
    with pytest.raises(OaSignedTokenError, match="active signing key"):
        repository.rotate_signing_keys(invalid_previous, planned_active)

    third = repository.save_signing_key(_key("oa-key-c"))
    repository.save_signing_key(
        plan_signing_key_transition(
            third, target_state="ACTIVE", expected_revision=1, now_epoch=430
        )
    )
    planned_previous = {
        **first,
        "state": "VERIFY_ONLY",
        "revision": 2,
        "previous_revision": 1,
    }
    with pytest.raises(OaSignedTokenError, match="active signing key"):
        repository.rotate_signing_keys(planned_previous, planned_active)


def test_repository_persists_finds_and_purges_revocations(repository) -> None:
    record = repository.create_revocation(_revocation())

    assert repository.get_revocation_by_digest(record["jti_digest"])["revocation_id"] == "rev-one"
    assert repository.purge_expired_revocations(at_epoch=899) == 0
    assert repository.purge_expired_revocations(at_epoch=900) == 1
    assert repository.get_revocation_by_digest(record["jti_digest"]) is None


def test_repository_rejects_duplicate_revocation_id_and_digest(repository) -> None:
    repository.create_revocation(_revocation())
    with pytest.raises(OaSignedTokenError, match="already exists"):
        repository.create_revocation(_revocation())
    with pytest.raises(OaSignedTokenError, match="already exists"):
        repository.create_revocation(_revocation("rev-two", "jti-one"))


def test_memory_repository_returns_copies_and_validates_digest() -> None:
    repository = InMemoryOaSignedTokenRepository()
    saved = repository.save_signing_key(_key("oa-key-copy"))
    saved["state"] = "REVOKED"
    assert repository.get_signing_key("oa-key-copy")["state"] == "PREPUBLISHED"
    assert repository.get_signing_key("oa-key-missing") is None
    with pytest.raises(OaSignedTokenError, match="digest is invalid"):
        repository.get_revocation_by_digest("bad")


def test_memory_repository_scans_multiple_revocations() -> None:
    repository = InMemoryOaSignedTokenRepository()
    repository.create_revocation(_revocation("rev-one", "jti-one"))
    second = repository.create_revocation(_revocation("rev-two", "jti-two"))
    assert repository.get_revocation_by_digest(second["jti_digest"])["revocation_id"] == "rev-two"


def test_runtime_builder_defaults_to_memory() -> None:
    runtime = build_service_persistence_runtime(
        service_id="nex-oa",
        database_env="NEX_OA_DATABASE_URL",
        environ={},
        mode=PERSISTENCE_MODE_MEMORY,
    )
    assert isinstance(
        build_signed_token_repository_for_runtime(runtime),
        InMemoryOaSignedTokenRepository,
    )


def test_runtime_builder_selects_sqlalchemy_for_postgres() -> None:
    factory = object()
    runtime = SimpleNamespace(
        mode=PERSISTENCE_MODE_POSTGRES,
        api_session_factory=factory,
    )
    result = build_signed_token_repository_for_runtime(runtime)
    assert isinstance(result, SqlAlchemyOaSignedTokenRepository)
    assert result._session_factory is factory


def test_sql_repository_maps_database_failures_to_unavailable() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyOaSignedTokenRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    with pytest.raises(OaSignedTokenError, match="persistence is unavailable"):
        repository.save_signing_key(_key("oa-key-missing-table"))
    with pytest.raises(OaSignedTokenError, match="persistence is unavailable"):
        repository.create_revocation(_revocation())
    with pytest.raises(OaSignedTokenError, match="persistence is unavailable"):
        repository.purge_expired_revocations(at_epoch=900)
    with pytest.raises(OaSignedTokenError, match="persistence is unavailable"):
        repository.list_signing_keys()
    with pytest.raises(OaSignedTokenError, match="persistence is unavailable"):
        repository.rotate_signing_keys(
            {**_key("oa-key-a"), "state": "VERIFY_ONLY", "revision": 2, "previous_revision": 1},
            {**_key("oa-key-b"), "state": "ACTIVE", "revision": 2, "previous_revision": 1},
        )
    engine.dispose()


def test_repository_value_helpers_cover_datetime_and_decode_branches() -> None:
    aware = datetime(1970, 1, 1, 0, 10, tzinfo=UTC)
    naive = datetime(1970, 1, 1, 0, 10)  # noqa: DTZ001 - exercises naive input
    assert repository_module._timestamp(aware) is aware
    assert repository_module._timestamp(naive).tzinfo is UTC
    assert repository_module._epoch("1970-01-01T00:10:00+00:00") == 600
    assert repository_module._epoch(600) == 600
    assert repository_module._decode_row(
        {"public_jwk": {"kid": "one"}, "expires_at": None},
        ("public_jwk",),
        ("expires_at",),
    )["public_jwk"] == {"kid": "one"}
    for invalid in (None, "x" * 63, "g" * 64):
        with pytest.raises(OaSignedTokenError, match="digest is invalid"):
            repository_module._normalize_digest(invalid)


_SQLITE_SCHEMA = """
CREATE TABLE oa_signing_keys (
    key_id TEXT PRIMARY KEY,
    signing_key_schema_version TEXT NOT NULL,
    issuer TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    state TEXT NOT NULL,
    public_jwk TEXT NOT NULL,
    private_key_ref TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL,
    activate_at TIMESTAMP NOT NULL,
    sign_until TIMESTAMP NOT NULL,
    verify_until TIMESTAMP NOT NULL,
    revision INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ux_oa_signing_keys_active
    ON oa_signing_keys (issuer) WHERE state = 'ACTIVE';
CREATE TABLE oa_token_revocations (
    revocation_id TEXT PRIMARY KEY,
    revocation_schema_version TEXT NOT NULL,
    jti_digest TEXT NOT NULL UNIQUE,
    issuer TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    audience TEXT NOT NULL,
    token_use TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    revoked_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
