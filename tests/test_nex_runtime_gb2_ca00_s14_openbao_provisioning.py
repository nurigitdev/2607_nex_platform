from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from nex_runtime import openbao_provisioning as provisioning
from nex_runtime.openbao_provisioning import (
    OpenBaoProvisioningError,
    OpenBaoProvisioningSession,
    provision_openbao_environment,
    reactivate_openbao_after_restart,
    verify_openbao_runtime_resolution,
)
from nex_runtime.production_secret_materialization import ResolvedSecret

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-28T12:00:00Z"


@dataclass(frozen=True)
class Binding:
    owner: str
    target_environment_name: str


BINDINGS = (
    Binding("nex-oa", "NEX_OA_DATABASE_URL"),
    Binding("nex-ae-api", "NEX_AE_DATABASE_URL"),
    Binding("nex-ae-api", "NEX_AE_TO_OA_SERVICE_TOKEN"),
)
OWNERS = ("nex-oa", "nex-ae-api")


def session() -> OpenBaoProvisioningSession:
    return OpenBaoProvisioningSession(
        owners=OWNERS,
        secret_count=3,
        secret_versions=(1,),
        trust_configured=False,
        checked_at=NOW,
        root_token="private-root-token",
        unseal_key="private-unseal-key",
    )


class Resolver:
    def __init__(self, *, change=None, raises: bool = False) -> None:
        self.change = change
        self.raises = raises
        self.revoked = False
        self.references: list[str] = []

    def resolve(self, reference, *, context):
        self.references.append(reference)
        if self.raises:
            raise RuntimeError("private provider detail")
        result = ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="openbao",
            value="private-secret-value",
        )
        return self.change(result) if self.change else result

    def revoke(self) -> None:
        self.revoked = True


class ResolverWithoutRevoke:
    def resolve(self, reference, *, context):
        return ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="openbao",
            value="private-secret-value",
        )


class ResolverWithBrokenRevoke(Resolver):
    def revoke(self) -> None:
        raise RuntimeError("private revoke detail")


def environments() -> dict[str, dict[str, str]]:
    return {owner: {"OWNER": owner} for owner in OWNERS}


def test_provisioning_delegates_to_existing_s143_and_s144_owners(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        provisioning,
        "initialize_openbao",
        lambda client, runtime_dir: SimpleNamespace(
            root_token="private-root-token", unseal_key="private-unseal-key"
        ),
    )

    def configure(client, **kwargs):
        calls.append(("configure", kwargs))
        return {"secret_count": 3, "secret_versions": [1]}

    monkeypatch.setattr(provisioning, "configure_openbao_staging", configure)
    monkeypatch.setattr(
        provisioning,
        "configure_openbao_s144_trust",
        lambda client, **kwargs: calls.append(("trust", kwargs)),
    )
    monkeypatch.setattr(
        provisioning,
        "refresh_openbao_s144_transit_credentials",
        lambda client, **kwargs: calls.append(("transit", kwargs)),
    )

    result = provision_openbao_environment(
        object(),
        root=ROOT,
        runtime_dir=tmp_path,
        secret_values={binding.target_environment_name: "private" for binding in BINDINGS},
        bindings=BINDINGS,
        owners=OWNERS,
        subject_alt_names=("oa.nex-staging.test",),
        configure_trust=True,
        checked_at="2026-10-28T21:00:00+09:00",
    )
    projection = result.to_projection()

    assert [name for name, _ in calls] == ["configure", "trust", "transit"]
    assert result.trust_configured is True
    assert result.checked_at == NOW
    assert projection["status"] == "PROVISIONED"
    assert projection["runtime_authorization_verified"] is False
    assert projection["dependency_readiness"]["ready"] is False
    assert projection["dependency_readiness"]["authorized"] is False
    assert "private-root-token" not in repr(result)
    assert "private-unseal-key" not in repr(result)
    assert "private" not in str(projection)


def test_provisioning_without_trust_keeps_runtime_boundary_separate(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        provisioning,
        "initialize_openbao",
        lambda client, runtime_dir: SimpleNamespace(root_token="root-token", unseal_key="key"),
    )
    monkeypatch.setattr(
        provisioning,
        "configure_openbao_staging",
        lambda client, **kwargs: {"secret_count": 3, "secret_versions": (1, 2)},
    )
    monkeypatch.setattr(
        provisioning,
        "configure_openbao_s144_trust",
        lambda *args, **kwargs: pytest.fail("trust must be opt-in"),
    )

    result = provision_openbao_environment(
        object(),
        root=ROOT,
        runtime_dir=tmp_path,
        secret_values={binding.target_environment_name: "private" for binding in BINDINGS},
        bindings=BINDINGS,
        owners=OWNERS,
        subject_alt_names=("oa.nex-staging.test",),
        checked_at=NOW,
    )

    assert result.secret_versions == (1, 2)
    assert result.trust_configured is False


def test_runtime_resolution_authenticates_each_owner_after_restart_and_revokes() -> None:
    first: list[Resolver] = []
    restarted: list[Resolver] = []

    def factory(target: list[Resolver]):
        def build(environment):
            resolver = Resolver()
            resolver.environment = environment
            target.append(resolver)
            return resolver

        return build

    initial = verify_openbao_runtime_resolution(
        session(),
        resolver_environments=environments(),
        bindings=BINDINGS,
        namespace="staging",
        reference_version="v1",
        secret_generation="secret:gb2-s14.1",
        checked_at=NOW,
        resolver_factory=factory(first),
    )
    after_restart = verify_openbao_runtime_resolution(
        session(),
        resolver_environments=environments(),
        bindings=tuple(reversed(BINDINGS)),
        namespace="staging",
        reference_version="v1",
        secret_generation="secret:gb2-s14.1",
        resolver_factory=factory(restarted),
    )

    assert initial["status"] == "READY"
    assert initial["resolved_owner_count"] == 2
    assert initial["dependency_readiness"]["ready"] is True
    assert initial["dependency_readiness"]["authorized"] is True
    assert initial["dependency_readiness"]["evidence_hash"] == after_restart[
        "dependency_readiness"
    ]["evidence_hash"]
    assert all(item.revoked for item in (*first, *restarted))
    assert first[0].references == [
        "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1"
    ]
    assert first[1].references == [
        "secret://openbao/nex-platform/staging/nex-ae-api/NEX_AE_DATABASE_URL@v1"
    ]
    assert "private-secret-value" not in str(initial)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: Resolver(raises=True), "runtime resolution failed"),
        (
            lambda: Resolver(change=lambda value: replace(value, owner="nex-cx")),
            "runtime resolution failed",
        ),
        (
            lambda: Resolver(change=lambda value: replace(value, provider_id="other")),
            "runtime resolution failed",
        ),
        (lambda: Resolver(change=lambda value: object()), "runtime resolution failed"),
    ],
)
def test_runtime_resolution_sanitizes_provider_and_metadata_failures(
    factory, message
) -> None:
    resolvers: list[Resolver] = []

    def build(environment):
        resolver = factory()
        resolvers.append(resolver)
        return resolver

    with pytest.raises(OpenBaoProvisioningError, match=message) as raised:
        verify_openbao_runtime_resolution(
            session(),
            resolver_environments=environments(),
            bindings=BINDINGS,
            namespace="staging",
            reference_version="v1",
            secret_generation="secret:gb2-s14.1",
            checked_at=NOW,
            resolver_factory=build,
        )

    assert "private provider detail" not in str(raised.value)
    assert resolvers[0].revoked is True


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda environment: ResolverWithoutRevoke(), "token revocation failed"),
        (lambda environment: ResolverWithBrokenRevoke(), "token revocation failed"),
    ],
)
def test_runtime_resolution_fails_closed_on_absent_or_failed_revoke(
    factory, message
) -> None:
    with pytest.raises(OpenBaoProvisioningError, match=message) as raised:
        verify_openbao_runtime_resolution(
            session(),
            resolver_environments=environments(),
            bindings=BINDINGS,
            namespace="staging",
            reference_version="v1",
            secret_generation="secret:gb2-s14.1",
            resolver_factory=factory,
        )

    assert "private revoke detail" not in str(raised.value)


def test_runtime_resolution_sanitizes_resolver_factory_failure() -> None:
    def broken_factory(environment):
        raise RuntimeError("private authentication detail")

    with pytest.raises(OpenBaoProvisioningError, match="nex-oa") as raised:
        verify_openbao_runtime_resolution(
            session(),
            resolver_environments=environments(),
            bindings=BINDINGS,
            namespace="staging",
            reference_version="v1",
            secret_generation="secret:gb2-s14.1",
            checked_at=NOW,
            resolver_factory=broken_factory,
        )

    assert "private authentication detail" not in str(raised.value)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"resolver_environments": {"nex-oa": {}}}, "owner coverage"),
        ({"namespace": "development"}, "namespace"),
        ({"reference_version": "latest"}, "reference version"),
        ({"secret_generation": "bad"}, "secret generation"),
        ({"checked_at": "not-a-time"}, "timestamp"),
        ({"checked_at": "2026-10-28T12:00:00"}, "timestamp"),
    ],
)
def test_runtime_resolution_rejects_invalid_admission(kwargs, message) -> None:
    inputs = {
        "resolver_environments": environments(),
        "bindings": BINDINGS,
        "namespace": "staging",
        "reference_version": "v1",
        "secret_generation": "secret:gb2-s14.1",
        "checked_at": NOW,
        "resolver_factory": lambda _: Resolver(),
    }
    inputs.update(kwargs)

    with pytest.raises(OpenBaoProvisioningError, match=message):
        verify_openbao_runtime_resolution(session(), **inputs)


@pytest.mark.parametrize(
    ("bindings", "owners", "message"),
    [
        ((), OWNERS, "empty"),
        (BINDINGS, ("nex-oa", "nex-oa"), "owner inventory"),
        (BINDINGS, ("unknown",), "owner inventory"),
        ((Binding("nex-oa", "bad"),), ("nex-oa",), "binding inventory"),
        ((object(),), ("nex-oa",), "binding inventory"),
    ],
)
def test_inventory_validation_fails_closed(bindings, owners, message) -> None:
    with pytest.raises(OpenBaoProvisioningError, match=message):
        provisioning._validate_inventory(bindings, owners)


def test_representative_binding_selection_rejects_missing_owner() -> None:
    with pytest.raises(OpenBaoProvisioningError, match="owner coverage"):
        provisioning._representative_bindings(BINDINGS[:1], OWNERS)


class RestartClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, object, object]] = []

    def request(self, method, path, *, token=None, payload=None):
        self.calls.append((method, path, token, payload))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_restart_reactivation_waits_unseals_and_returns_redacted_evidence() -> None:
    client = RestartClient(
        [
            RuntimeError("private startup detail"),
            {"initialized": True, "sealed": True},
            {},
            {"ha_enabled": True, "is_self": True},
        ]
    )
    sleeps: list[float] = []

    result = reactivate_openbao_after_restart(
        client,
        session(),
        attempts=3,
        interval_seconds=0.25,
        sleep=sleeps.append,
    )

    assert result == {
        "schema_version": "openbao_provisioning.v1",
        "status": "REACTIVATED",
        "attempts": 2,
        "custody_material_included": False,
    }
    assert sleeps == [0.25]
    assert client.calls[2] == (
        "PUT",
        "/v1/sys/unseal",
        None,
        {"key": "private-unseal-key"},
    )
    assert "private-unseal-key" not in str(result)


def test_restart_reactivation_accepts_already_unsealed_node() -> None:
    client = RestartClient(
        [
            {"initialized": True, "sealed": False},
            {"ha_enabled": True, "is_self": True},
        ]
    )

    result = reactivate_openbao_after_restart(client, session())

    assert result["status"] == "REACTIVATED"
    assert all(call[1] != "/v1/sys/unseal" for call in client.calls)


@pytest.mark.parametrize(
    ("attempts", "interval", "message"),
    [
        (0, 0.1, "policy"),
        (1, -0.1, "policy"),
    ],
)
def test_restart_reactivation_rejects_invalid_retry_policy(
    attempts, interval, message
) -> None:
    with pytest.raises(OpenBaoProvisioningError, match=message):
        reactivate_openbao_after_restart(
            RestartClient([]),
            session(),
            attempts=attempts,
            interval_seconds=interval,
        )


def test_restart_reactivation_fails_closed_for_uninitialized_or_unready_node() -> None:
    with pytest.raises(OpenBaoProvisioningError, match="not initialized"):
        reactivate_openbao_after_restart(
            RestartClient([{"initialized": False, "sealed": True}]),
            session(),
        )

    with pytest.raises(OpenBaoProvisioningError, match="did not become ready"):
        reactivate_openbao_after_restart(
            RestartClient(
                [
                    {"initialized": True, "sealed": False},
                    {"ha_enabled": True, "is_self": False},
                ]
            ),
            session(),
            attempts=1,
        )


@pytest.mark.parametrize(
    ("configured", "message"),
    [
        ({"secret_count": 0, "secret_versions": [1]}, "secret_count"),
        ({"secret_count": True, "secret_versions": [1]}, "secret_count"),
        ({"secret_count": 1, "secret_versions": []}, "versions"),
        ({"secret_count": 1, "secret_versions": "v1"}, "versions"),
        ({"secret_count": 1, "secret_versions": [False]}, "versions"),
    ],
)
def test_provisioning_rejects_invalid_safe_projection(
    monkeypatch, tmp_path: Path, configured, message
) -> None:
    monkeypatch.setattr(
        provisioning,
        "initialize_openbao",
        lambda client, runtime_dir: SimpleNamespace(root_token="root", unseal_key="key"),
    )
    monkeypatch.setattr(
        provisioning, "configure_openbao_staging", lambda client, **kwargs: configured
    )

    with pytest.raises(OpenBaoProvisioningError, match=message):
        provision_openbao_environment(
            object(),
            root=ROOT,
            runtime_dir=tmp_path,
            secret_values={
                binding.target_environment_name: "private" for binding in BINDINGS
            },
            bindings=BINDINGS,
            owners=OWNERS,
            subject_alt_names=("oa.nex-staging.test",),
            checked_at=NOW,
        )


def test_p8_demo_is_a_consumer_of_canonical_provisioning() -> None:
    source = (ROOT / "scripts/deployment/run_p8_demo_trust_admission.py").read_text(
        encoding="utf-8"
    )

    assert "from nex_runtime.openbao_provisioning import" in source
    assert "provision_openbao_environment(" in source
    assert "reactivate_openbao_after_restart(" in source
    assert "verify_openbao_runtime_resolution(" in source
    assert "initialize_openbao(" not in source
    assert "configure_openbao_staging(" not in source
