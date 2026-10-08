from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import nex_runtime.production_configuration as production_configuration
from nex_runtime.production_configuration import (
    PRODUCTION_CONFIGURATION_MANIFEST_PATH,
    PRODUCTION_CONFIGURATION_SCHEMA_VERSION,
    PRODUCTION_CONTROL_ENV_NAMES,
    ProductionConfigurationError,
    _required_string_mapping,
    _required_string_sequence,
    _secret_owner,
    build_default_production_configuration_manifest,
    load_production_configuration_manifest,
    production_configuration_manifest_projection,
    validate_production_configuration_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def test_repository_manifest_matches_typed_default_and_is_metadata_only() -> None:
    loaded = load_production_configuration_manifest(ROOT)
    default = build_default_production_configuration_manifest()
    projection = production_configuration_manifest_projection(loaded)

    assert loaded == default
    assert projection["schema_version"] == PRODUCTION_CONFIGURATION_SCHEMA_VERSION
    assert projection["profile"] == "production"
    assert projection["binding_count"] == 31
    assert projection["secret_reference_count"] == 20
    assert projection["public_connection_count"] == 11
    assert projection["control_environment_count"] == 6
    assert projection["control_environment_names"] == list(
        PRODUCTION_CONTROL_ENV_NAMES
    )
    assert projection["raw_secret_values_included"] is False
    assert projection["reference_values_included"] is False
    assert projection["connection_values_included"] is False


def test_secret_owners_and_reference_bindings_are_exact() -> None:
    manifest = build_default_production_configuration_manifest()
    secrets = [
        item for item in manifest.bindings
        if item.input_kind == "external_secret_reference"
    ]

    assert len(secrets) == 20
    assert all(
        item.source_environment_name == f"{item.target_environment_name}_REF"
        for item in secrets
    )
    assert _secret_owner("NEX_AE_TO_CX_SERVICE_TOKEN") == "nex-ae-api"
    assert _secret_owner("NEX_CX_TO_MO_SERVICE_TOKEN") == "nex-cx"
    assert _secret_owner("NEX_AG_TO_OA_SERVICE_TOKEN") == "nex-ag"
    assert _secret_owner("NEX_OA_DATABASE_URL") == "nex-oa"
    assert _secret_owner("NEX_MO_VLLM_API_KEY") == "nex-mo"
    assert _secret_owner("NEX_CX_OBJECT_STORAGE_SECRET_KEY") == "nex-cx"
    assert _secret_owner("NEX_AE_OBJECT_STORAGE_ACCESS_KEY") == "nex-ae-api"
    with pytest.raises(ProductionConfigurationError, match="owner is unknown"):
        _secret_owner("UNKNOWN_SECRET")


def test_validation_reports_schema_profile_coverage_owner_and_binding_drift() -> None:
    manifest = build_default_production_configuration_manifest()
    bindings = list(manifest.bindings)
    bindings[0] = replace(
        bindings[0],
        source_environment_name=bindings[1].source_environment_name,
        owner="unknown",
        input_kind="public_connection",
    )
    bindings[-1] = replace(bindings[-1], source_environment_name="changed")
    with pytest.raises(ProductionConfigurationError) as raised:
        validate_production_configuration_manifest(
            replace(
                manifest,
                schema_version="wrong",
                profile="test",
                bindings=tuple((*bindings, bindings[-1])),
                control_environment_names=(),
            )
        )

    detail = str(raised.value)
    assert "schema version drift" in detail
    assert "profile drift" in detail
    assert "target coverage or order drift" in detail
    assert "targets must be unique" in detail
    assert "sources must be unique" in detail
    assert "owner is invalid" in detail
    assert "secret reference binding drift" in detail
    assert "public connection binding drift" in detail
    assert "control environment coverage" in detail


def test_loader_rejects_unreadable_nonobject_invalid_fields_and_drift(
    tmp_path: Path, monkeypatch,
) -> None:
    with pytest.raises(ProductionConfigurationError, match="unreadable"):
        load_production_configuration_manifest(tmp_path)

    path = tmp_path / PRODUCTION_CONFIGURATION_MANIFEST_PATH
    path.parent.mkdir(parents=True)
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ProductionConfigurationError, match="must be an object"):
        load_production_configuration_manifest(tmp_path)

    path.write_text("schema_version: wrong\n", encoding="utf-8")
    with pytest.raises(ProductionConfigurationError, match="field is invalid"):
        load_production_configuration_manifest(tmp_path)

    path.write_text(
        (ROOT / PRODUCTION_CONFIGURATION_MANIFEST_PATH)
        .read_text(encoding="utf-8")
        .replace("profile: production", "profile: staging_live"),
        encoding="utf-8",
    )
    with pytest.raises(ProductionConfigurationError, match="profile drift"):
        load_production_configuration_manifest(tmp_path)

    path.write_text(
        (ROOT / PRODUCTION_CONFIGURATION_MANIFEST_PATH)
        .read_text(encoding="utf-8")
        .replace(
            "NEX_TLS_TRUST_BUNDLE_REF", "NEX_TLS_DIFFERENT_TRUST_BUNDLE_REF"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProductionConfigurationError, match="coverage or order"):
        load_production_configuration_manifest(tmp_path)

    path.write_text(
        (ROOT / PRODUCTION_CONFIGURATION_MANIFEST_PATH).read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    canonical = build_default_production_configuration_manifest()
    monkeypatch.setattr(
        production_configuration,
        "build_default_production_configuration_manifest",
        lambda: replace(canonical, profile="different"),
    )
    with pytest.raises(ProductionConfigurationError, match="manifest drift"):
        load_production_configuration_manifest(tmp_path)


def test_low_level_manifest_field_helpers_reject_invalid_values() -> None:
    assert _required_string_mapping({"a": "b"}, "mapping") == {"a": "b"}
    for value in ({}, [], {"": "b"}, {"a": ""}, {1: "b"}, {"a": 1}):
        with pytest.raises(TypeError, match="string mapping"):
            _required_string_mapping(value, "mapping")

    assert _required_string_sequence(["a", "b"], "sequence") == ("a", "b")
    for value in ([], "a", [""], [1]):
        with pytest.raises(TypeError, match="string list"):
            _required_string_sequence(value, "sequence")
