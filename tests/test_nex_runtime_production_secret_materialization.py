from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from nex_runtime.production_configuration import (
    build_default_production_configuration_manifest,
)
from nex_runtime.production_secret_materialization import (
    OwnerSecretEnvironment,
    ProductionSecretMaterializationError,
    ResolvedSecret,
    SecretResolutionContext,
    materialize_production_secrets,
    production_secret_materialization_projection,
)
from run_platform_production_startup_admission import _synthetic_environment


ROOT = Path(__file__).resolve().parents[1]


class Resolver:
    def __init__(self, change=None, *, raises=False) -> None:
        self.change = change
        self.raises = raises

    def resolve(self, reference, *, context):
        if self.raises:
            raise RuntimeError("sensitive provider diagnostics")
        secret = ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id=urlsplit(reference).hostname,
            value=f"value-for-{context.target_environment_name}",
        )
        return self.change(secret) if self.change else secret


def test_materializes_exact_owner_scoped_environments_without_mutating_input() -> None:
    environment = _synthetic_environment(ROOT)
    original = dict(environment)
    result = materialize_production_secrets(environment, Resolver(), root=ROOT)
    projection = production_secret_materialization_projection(result)

    assert environment == original
    assert projection["status"] == "MATERIALIZED_FOR_OWNER_PROCESSES"
    assert projection["owner_count"] == 5
    assert projection["secret_count"] == 16
    assert projection["raw_secret_values_included"] is False
    assert len(result.environment_for("nex-mo")) == 4
    assert set(result.environment_for("nex-oa")) == {
        "NEX_OA_DATABASE_URL",
        "NEX_OA_INTROSPECTION_SERVICE_TOKEN",
    }
    with pytest.raises(ProductionSecretMaterializationError, match="unknown"):
        result.environment_for("nex-unknown")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: object(), "result is invalid"),
        (lambda value: replace(value, owner="other"), "metadata mismatch"),
        (lambda value: replace(value, target_environment_name="OTHER"), "metadata mismatch"),
        (lambda value: replace(value, secret_generation="secret:other"), "metadata mismatch"),
        (lambda value: replace(value, reference_version="other"), "metadata mismatch"),
        (lambda value: replace(value, provider_id="other"), "metadata mismatch"),
        (lambda value: replace(value, value=""), "value is invalid"),
        (lambda value: replace(value, value="placeholder"), "value is invalid"),
        (lambda value: replace(value, value="bad\nvalue"), "value is invalid"),
        (lambda value: replace(value, value=123), "value is invalid"),
    ],
)
def test_rejects_invalid_resolver_results(change, message) -> None:
    with pytest.raises(ProductionSecretMaterializationError, match=message):
        materialize_production_secrets(
            _synthetic_environment(ROOT), Resolver(change), root=ROOT
        )


def test_sanitizes_resolver_exception() -> None:
    with pytest.raises(ProductionSecretMaterializationError) as caught:
        materialize_production_secrets(
            _synthetic_environment(ROOT), Resolver(raises=True), root=ROOT
        )
    assert "sensitive" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_rejects_invalid_admitted_reference_metadata_and_coverage(monkeypatch) -> None:
    environment = _synthetic_environment(ROOT)
    environment["NEX_OA_DATABASE_URL_REF"] = "secret://external/path-without-version"
    with pytest.raises(ValueError, match="reference"):
        materialize_production_secrets(environment, Resolver(), root=ROOT)

    manifest = build_default_production_configuration_manifest()
    reduced = replace(manifest, bindings=manifest.bindings[1:])
    monkeypatch.setattr(
        "nex_runtime.production_secret_materialization.admit_production_startup",
        lambda *args, **kwargs: type("Admission", (), {"configuration_digest": "sha256:" + "0" * 64})(),
    )
    with pytest.raises(ProductionSecretMaterializationError, match="coverage drift"):
        materialize_production_secrets(
            _synthetic_environment(ROOT), Resolver(), root=ROOT, manifest=reduced
        )


def test_projection_rejects_invalid_header_and_coverage() -> None:
    result = materialize_production_secrets(
        _synthetic_environment(ROOT), Resolver(), root=ROOT
    )
    with pytest.raises(ProductionSecretMaterializationError, match="projection is invalid"):
        production_secret_materialization_projection(replace(result, status="OTHER"))
    with pytest.raises(ProductionSecretMaterializationError, match="coverage drift"):
        production_secret_materialization_projection(
            replace(
                result,
                owner_environments=(OwnerSecretEnvironment("nex-oa", ()),),
            )
        )


def test_reference_metadata_defense_after_admission(monkeypatch) -> None:
    monkeypatch.setattr(
        "nex_runtime.production_secret_materialization.admit_production_startup",
        lambda *args, **kwargs: type("Admission", (), {"configuration_digest": "sha256:" + "0" * 64})(),
    )
    environment = _synthetic_environment(ROOT)
    environment["NEX_OA_DATABASE_URL_REF"] = "secret:/missing-host@"
    with pytest.raises(ProductionSecretMaterializationError, match="metadata is invalid"):
        materialize_production_secrets(environment, Resolver(), root=ROOT)

    environment["NEX_OA_DATABASE_URL_REF"] = "secret://external/no-version"
    with pytest.raises(ProductionSecretMaterializationError, match="metadata is invalid"):
        materialize_production_secrets(environment, Resolver(), root=ROOT)
