from __future__ import annotations

import pytest

from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError


SECRET_ONE = "first-client-secret-value"
SECRET_TWO = "second-client-secret-value"


def _service() -> tuple[OaServicePrincipalService, InMemoryOaServicePrincipalRepository]:
    repository = InMemoryOaServicePrincipalRepository()
    service = OaServicePrincipalService(repository)
    service.upsert_principal(
        {
            "principal_id": "ae-runtime",
            "service_id": "nex-ae-api",
            "display_name": "AE Runtime",
            "allowed_audiences": ["nex-cx"],
            "allowed_scopes": ["document:read"],
            "expected_revision": 0,
        }
    )
    return service, repository


def test_issue_returns_secret_once_and_persists_only_argon2id_hash() -> None:
    service, repository = _service()

    issued = service.issue_credential(
        "ae-runtime",
        lifetime_days=30,
        now_epoch=1_000,
        credential_id="cred-one",
        client_secret=SECRET_ONE,
    )
    listed = service.list_credentials("ae-runtime")
    fetched = service.get_credential("cred-one")

    assert issued["client_secret"] == SECRET_ONE
    assert issued["secret_display"] == "once"
    assert "secret_hash" not in issued["credential"]
    assert "client_secret" not in listed["items"][0]
    assert "secret_hash" not in fetched["credential"]
    assert repository.credentials["cred-one"]["secret_hash"].startswith("$argon2id$")
    assert repository.credentials["cred-one"]["secret_hint"] == SECRET_ONE[-6:]
    assert service.verify_client_secret(
        "cred-one", SECRET_ONE, now_epoch=1_001
    ) == {"principal_id": "ae-runtime", "credential_id": "cred-one"}


def test_rotation_is_atomic_and_old_secret_obeys_grace() -> None:
    service, repository = _service()
    service.issue_credential(
        "ae-runtime",
        lifetime_days=30,
        now_epoch=1_000,
        credential_id="cred-one",
        client_secret=SECRET_ONE,
    )

    rotated = service.rotate_credential(
        "cred-one",
        expected_revision=1,
        lifetime_days=60,
        grace_seconds=300,
        now_epoch=2_000,
        new_credential_id="cred-two",
        client_secret=SECRET_TWO,
    )

    assert rotated["rotated_credential"]["status"] == "ROTATING"
    assert rotated["rotated_credential"]["grace_until"] == 2_300
    assert rotated["credential"]["credential_id"] == "cred-two"
    assert rotated["client_secret"] == SECRET_TWO
    assert service.verify_client_secret("cred-one", SECRET_ONE, now_epoch=2_300)
    assert service.verify_client_secret("cred-two", SECRET_TWO, now_epoch=2_301)
    with pytest.raises(OaServicePrincipalError):
        service.verify_client_secret("cred-one", SECRET_ONE, now_epoch=2_301)
    assert set(repository.credentials) == {"cred-one", "cred-two"}


def test_revoke_and_rejected_secret_paths() -> None:
    service, _ = _service()
    service.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=1_000,
        credential_id="cred-one",
        client_secret=SECRET_ONE,
    )
    revoked = service.set_credential_status(
        "cred-one",
        target_status="REVOKED",
        expected_revision=1,
        now_epoch=1_100,
    )
    assert revoked["credential"]["status"] == "REVOKED"
    with pytest.raises(OaServicePrincipalError) as rejected:
        service.verify_client_secret("cred-one", SECRET_ONE, now_epoch=1_101)
    assert rejected.value.status_code == 401

    for credential_id, secret in (("missing", SECRET_ONE), ("cred-one", "")):
        with pytest.raises(OaServicePrincipalError):
            service.verify_client_secret(credential_id, secret, now_epoch=1_000)


def test_expired_wrong_and_malformed_hash_credentials_are_rejected() -> None:
    service, repository = _service()
    service.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=1_000,
        credential_id="cred-one",
        client_secret=SECRET_ONE,
    )
    with pytest.raises(OaServicePrincipalError):
        service.verify_client_secret("cred-one", SECRET_TWO, now_epoch=1_001)
    with pytest.raises(OaServicePrincipalError):
        service.verify_client_secret("cred-one", SECRET_ONE, now_epoch=90_000)

    repository.credentials["cred-one"]["secret_hash"] = "malformed"
    with pytest.raises(OaServicePrincipalError):
        service.verify_client_secret("cred-one", SECRET_ONE, now_epoch=1_001)


def test_credential_missing_disabled_limit_and_stale_paths_fail_closed() -> None:
    service, repository = _service()
    with pytest.raises(OaServicePrincipalError) as missing_principal:
        service.issue_credential("missing", lifetime_days=1, now_epoch=1_000)
    with pytest.raises(OaServicePrincipalError) as missing_credential:
        service.get_credential("missing")
    with pytest.raises(OaServicePrincipalError):
        service.set_credential_status(
            "missing", target_status="REVOKED", expected_revision=1, now_epoch=1_000
        )
    with pytest.raises(OaServicePrincipalError):
        service.rotate_credential(
            "missing",
            expected_revision=1,
            lifetime_days=1,
            grace_seconds=1,
            now_epoch=1_000,
        )
    assert missing_principal.value.status_code == 404
    assert missing_credential.value.error_code == "oa.service_credential_not_found"

    service.set_principal_status(
        "ae-runtime", target_status="DISABLED", expected_revision=1
    )
    with pytest.raises(OaServicePrincipalError) as disabled:
        service.issue_credential("ae-runtime", lifetime_days=1, now_epoch=1_000)
    assert disabled.value.error_code == "oa.service_principal_disabled"

    repository.principals["ae-runtime"]["status"] = "ACTIVE"
    service.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=1_000,
        credential_id="cred-one",
        client_secret=SECRET_ONE,
    )
    service.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=1_000,
        credential_id="cred-two",
        client_secret=SECRET_TWO,
    )
    with pytest.raises(OaServicePrincipalError) as limit:
        service.issue_credential("ae-runtime", lifetime_days=1, now_epoch=1_000)
    assert limit.value.error_code == "oa.service_credential_active_limit"
    with pytest.raises(OaServicePrincipalError):
        service.rotate_credential(
            "cred-one",
            expected_revision=99,
            lifetime_days=1,
            grace_seconds=1,
            now_epoch=1_100,
        )

    del repository.principals["ae-runtime"]
    with pytest.raises(OaServicePrincipalError) as missing_rotation_principal:
        service.rotate_credential(
            "cred-one",
            expected_revision=1,
            lifetime_days=1,
            grace_seconds=1,
            now_epoch=1_100,
        )
    assert missing_rotation_principal.value.status_code == 404


def test_default_clock_and_generators_produce_canonical_values() -> None:
    service, repository = _service()
    issued = service.issue_credential("ae-runtime", lifetime_days=1)

    assert issued["credential"]["credential_id"].startswith("cred-")
    assert len(issued["client_secret"]) >= 32
    assert repository.credentials[issued["credential"]["credential_id"]][
        "issued_at"
    ] > 0

    rotated = service.rotate_credential(
        issued["credential"]["credential_id"],
        expected_revision=1,
        lifetime_days=1,
        grace_seconds=60,
    )
    assert rotated["credential"]["credential_id"].startswith("cred-")


def test_false_hasher_verification_fails_closed(monkeypatch) -> None:
    service, _ = _service()
    service.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=1_000,
        credential_id="cred-one",
        client_secret=SECRET_ONE,
    )

    class FalseHasher:
        def verify(self, *_args):
            return False

    import nex_oa.service_principal_service as module

    monkeypatch.setattr(module, "_CREDENTIAL_HASHER", FalseHasher())
    with pytest.raises(OaServicePrincipalError):
        service.verify_client_secret("cred-one", SECRET_ONE, now_epoch=1_001)
