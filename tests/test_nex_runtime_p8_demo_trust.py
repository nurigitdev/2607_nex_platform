from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from nex_runtime import demo_trust
from nex_runtime.demo_trust import (
    DEMO_OWNERS,
    DEMO_SECRET_BINDINGS,
    DemoTrustError,
    DemoTrustGrant,
    demo_secret_bindings_for_owner,
    demo_startup_credential_bindings_for_owner,
    demo_trust_projection,
    materialize_demo_owner_secrets,
)
from nex_runtime.production_container_bootstrap import (
    prepare_production_container_environment,
)
from nex_runtime.production_secret_materialization import ResolvedSecret
from nex_runtime.s143_staging import (
    S143StagingError,
    prepare_staging_runtime_directory,
)
from run_p8_demo_trust_admission import (
    DemoTrustAdmissionError,
    _source_admission,
    run_p8_demo_trust_admission,
    summary_line,
)

ROOT = Path(__file__).resolve().parents[1]


class Resolver:
    def __init__(self, change=None, *, raises: bool = False) -> None:
        self.change = change
        self.raises = raises
        self.revoked = False

    def resolve(self, reference, *, context):
        if self.raises:
            raise RuntimeError("private provider detail")
        value = ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="openbao",
            value=f"private-{context.target_environment_name}",
        )
        return self.change(value) if self.change else value

    def revoke(self):
        self.revoked = True


def _environment(
    owner: str = "nex-wc", *, profile: str = "staging_live"
) -> dict[str, str]:
    namespace = "staging" if profile == "staging_live" else "production"
    result = {
        "NEX_PROFILE": profile,
        "NEX_DEPLOYMENT_BOUNDARY": "P8_DEMO",
        "NEX_SECRET_GENERATION": "secret:p8-demo.1",
        "NEX_OPENBAO_ROLE_ID_FILE": "/run/secrets/role",
        "NEX_OPENBAO_SECRET_ID_FILE": "/run/secrets/secret",
    }
    for binding in demo_secret_bindings_for_owner(owner):
        result[binding.source_environment_name] = (
            f"secret://openbao/nex-platform/{namespace}/{owner}/"
            f"{binding.target_environment_name}@v1"
        )
    return result


def test_inventory_covers_seven_owners_all_trust_slots_and_thirteen_tls_hosts() -> None:
    projection = demo_trust_projection()

    assert projection == {
        "schema_version": "p8_demo_trust.v1",
        "deployment_boundary": "P8_DEMO",
        "owner_count": 7,
        "secret_binding_count": 31,
        "trust_grant_count": 16,
        "tls_host_count": 13,
        "owner_secret_counts": {
            "nex-oa": 2,
            "nex-ae-api": 9,
            "nex-cx": 4,
            "nex-mo": 4,
            "nex-ag": 5,
            "nex-wc": 3,
            "nex-eos": 4,
        },
        "raw_secret_values_included": False,
        "token_values_included": False,
    }
    assert len(DEMO_SECRET_BINDINGS) == 31
    with pytest.raises(DemoTrustError, match="owner"):
        demo_secret_bindings_for_owner("nex-unknown")
    assert demo_startup_credential_bindings_for_owner("nex-oa") == ()
    assert len(demo_startup_credential_bindings_for_owner("nex-eos")) == 2
    with pytest.raises(DemoTrustError, match="owner"):
        demo_startup_credential_bindings_for_owner("nex-unknown")


def test_owner_materialization_is_deterministic_scoped_and_value_free() -> None:
    environment = _environment()
    resolver = Resolver()
    result = materialize_demo_owner_secrets(
        environment,
        resolver,
        owner="nex-wc",
        profile="staging_live",
    )
    repeated = materialize_demo_owner_secrets(
        environment,
        Resolver(),
        owner="nex-wc",
        profile="staging_live",
    )

    assert result.configuration_digest == repeated.configuration_digest
    assert result.materialization_digest == repeated.materialization_digest
    assert result.owner_environment.owner == "nex-wc"
    assert set(result.owner_environment.process_environment()) == {
        "NEX_WC_DATABASE_URL",
        "NEX_WC_TO_OA_SERVICE_TOKEN",
        "NEX_WC_TO_AE_SERVICE_TOKEN",
    }
    assert "private-" not in repr(result)

    production = materialize_demo_owner_secrets(
        _environment(profile="production"),
        Resolver(),
        owner="nex-wc",
        profile="production",
    )
    assert production.profile == "production"

    with pytest.raises(DemoTrustError, match="profile"):
        materialize_demo_owner_secrets(
            environment,
            Resolver(),
            owner="nex-wc",
            profile="test",
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda env: env.update(NEX_DEPLOYMENT_BOUNDARY="OTHER"), "boundary"),
        (lambda env: env.update(NEX_SECRET_GENERATION="bad"), "generation"),
        (lambda env: env.pop("NEX_WC_DATABASE_URL_REF"), "reference"),
        (
            lambda env: env.update(
                NEX_WC_DATABASE_URL_REF=(
                    "secret://openbao/nex-platform/staging/nex-eos/"
                    "NEX_WC_DATABASE_URL@v1"
                )
            ),
            "reference",
        ),
        (lambda env: env.update(NEX_WC_DATABASE_URL="raw"), "raw Demo secret"),
        (
            lambda env: env.update(
                NEX_WC_DATABASE_URL_REF=(
                    "secret://openbao/nex-platform/staging/nex-wc/"
                    "NEX_WC_DATABASE_URL@latest"
                )
            ),
            "reference",
        ),
    ],
)
def test_materialization_fails_closed_on_boundary_reference_and_raw_input(
    mutate, message
) -> None:
    environment = _environment()
    mutate(environment)
    with pytest.raises(DemoTrustError, match=message):
        materialize_demo_owner_secrets(
            environment,
            Resolver(),
            owner="nex-wc",
            profile="staging_live",
        )


@pytest.mark.parametrize(
    ("resolver", "message"),
    [
        (Resolver(raises=True), "resolution failed"),
        (Resolver(lambda value: object()), "result is invalid"),
        (Resolver(lambda value: replace(value, owner="nex-eos")), "metadata mismatch"),
        (
            Resolver(lambda value: replace(value, provider_id="other")),
            "metadata mismatch",
        ),
        (
            Resolver(lambda value: replace(value, value="bad\nvalue")),
            "value is invalid",
        ),
    ],
)
def test_materialization_sanitizes_provider_and_metadata_failures(
    resolver, message
) -> None:
    with pytest.raises(DemoTrustError, match=message) as raised:
        materialize_demo_owner_secrets(
            _environment(), resolver, owner="nex-wc", profile="staging_live"
        )
    assert "private provider detail" not in str(raised.value)


def test_production_bootstrap_selects_demo_inventory_and_scrubs_references() -> None:
    resolver = Resolver()
    process_environment, result = prepare_production_container_environment(
        "nex-eos",
        _environment("nex-eos"),
        root=ROOT,
        resolver_factory=lambda _: resolver,
    )

    assert resolver.revoked is True
    assert result.owner_environment.owner == "nex-eos"
    assert set(result.owner_environment.process_environment()) == {
        "NEX_EOS_DATABASE_URL",
        "NEX_EOS_TO_WC_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
    }
    assert not any(name.endswith("_REF") for name in process_environment)
    assert "NEX_OPENBAO_SECRET_ID_FILE" not in process_environment


def test_s143_runtime_helper_supports_additive_owner_inventory(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    prepare_staging_runtime_directory(runtime, owners=DEMO_OWNERS)
    credentials = {path.name for path in (runtime / "credentials").iterdir()}

    assert len(credentials) == 14
    assert "nex-wc.role-id" in credentials
    assert "nex-eos.secret-id" in credentials
    with pytest.raises(S143StagingError, match="owner inventory"):
        prepare_staging_runtime_directory(tmp_path / "invalid", owners=("bad",))


def test_source_admission_and_skip_are_metadata_only(tmp_path: Path) -> None:
    source = _source_admission(ROOT, inventory=demo_trust_projection())
    skipped = run_p8_demo_trust_admission({}, root=ROOT)

    assert source["source_admitted"] is True
    assert source["compose_source_count"] == 4
    assert skipped["status"] == "SOURCE_ADMITTED"
    assert skipped["executed"] is False
    assert "owners=8" in summary_line(skipped)

    for relative in (
        "deployment/compose/s143-staging.compose.yaml",
        "deployment/compose/s146-object-storage.override.yaml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(DemoTrustAdmissionError, match="unavailable"):
        _source_admission(tmp_path, inventory=demo_trust_projection())


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("_SECRET_TARGETS_BY_OWNER", {"nex-oa": ("NEX_OA_DATABASE_URL",)}),
        (
            "DEMO_SECRET_BINDINGS",
            (*DEMO_SECRET_BINDINGS, DEMO_SECRET_BINDINGS[0]),
        ),
        (
            "DEMO_TRUST_GRANTS",
            (
                *demo_trust.DEMO_TRUST_GRANTS,
                demo_trust.DEMO_TRUST_GRANTS[0],
            ),
        ),
        (
            "DEMO_TRUST_GRANTS",
            (
                *demo_trust.DEMO_TRUST_GRANTS,
                DemoTrustGrant(
                    "NEX_UNKNOWN_SERVICE_TOKEN",
                    "nex-oa",
                    "nex-eos",
                    ("service:call",),
                ),
            ),
        ),
        (
            "DEMO_TLS_HOSTS",
            (*demo_trust.DEMO_TLS_HOSTS, demo_trust.DEMO_TLS_HOSTS[0]),
        ),
    ],
)
def test_inventory_projection_detects_duplicate_drift(monkeypatch, name, value) -> None:
    monkeypatch.setattr(demo_trust, name, value)
    with pytest.raises(DemoTrustError, match="inventory drift"):
        demo_trust_projection()
