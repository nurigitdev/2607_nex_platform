from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.deployment_environments import (
    ARTIFACT_REFERENCE_ENVIRONMENTS,
    DEFAULT_ENVIRONMENT_COMPOSITIONS,
    ENVIRONMENT_COMPOSITION_SCHEMA_VERSION,
    EnvironmentCompositionError,
    _required_bool,
    _required_string_sequence,
    _validated_image_reference,
    build_default_environment_compositions,
    environment_composition_manifest_projection,
    environment_composition_projection,
    load_environment_compositions,
    required_environment_names_for_composition,
    resolve_environment_composition,
    validate_environment_compositions,
)
from nex_runtime.runtime_profiles import RuntimeProfileError

import run_platform_environment_compositions as smoke


ROOT = Path(__file__).resolve().parents[1]


def test_repository_environment_manifests_match_typed_defaults() -> None:
    defaults = build_default_environment_compositions()
    loaded = load_environment_compositions(ROOT)

    assert loaded == defaults == DEFAULT_ENVIRONMENT_COMPOSITIONS
    assert [item.environment_class for item in loaded] == [
        "development",
        "test",
        "staging",
        "production",
    ]
    assert {
        profile for item in loaded for profile in item.runtime_profiles
    } == {"local_mock", "local_live", "test", "staging_live", "production"}
    assert environment_composition_manifest_projection(loaded[0]) == {
        "schema_version": ENVIRONMENT_COMPOSITION_SCHEMA_VERSION,
        "environment_class": "development",
        "runtime_profiles": ["local_mock", "local_live"],
        "artifact_reference_policy": "local_build_or_digest",
        "immutable_artifacts_required": False,
        "allow_loopback": True,
        "allow_local_storage": True,
        "secret_source": "local_environment",
        "production_contact_allowed": False,
        "admitted_background_profiles": ["local_mock"],
    }


def test_all_profile_resolutions_are_private_and_fail_closed() -> None:
    definitions = load_environment_compositions(ROOT)
    projections = {}
    for profile in ("local_mock", "local_live", "test", "staging_live", "production"):
        resolution = resolve_environment_composition(
            profile,
            environ=smoke._synthetic_environment(profile),
            definitions=definitions,
        )
        projections[profile] = environment_composition_projection(resolution)

    assert projections["local_mock"]["status"] == "LIMITED"
    assert projections["test"]["status"] == "LIMITED"
    assert projections["test"]["artifact_reference_count"] == 6
    assert projections["local_live"]["status"] == "BLOCKED"
    assert projections["staging_live"]["status"] == "BLOCKED"
    assert projections["production"]["reason_codes"] == [
        "background_execution_profile_not_admitted",
        "production_deployment_approval_deferred",
    ]
    assert all(
        projection["artifact_reference_values_included"] is False
        for projection in projections.values()
    )


def test_resolution_rejects_runtime_and_artifact_configuration_failures() -> None:
    with pytest.raises(EnvironmentCompositionError, match="required environment"):
        resolve_environment_composition("test", environ={})

    environment = smoke._synthetic_environment("test")
    missing_name = next(iter(ARTIFACT_REFERENCE_ENVIRONMENTS.values()))
    environment.pop(missing_name)
    with pytest.raises(EnvironmentCompositionError, match=missing_name):
        resolve_environment_composition("test", environ=environment)

    environment = smoke._synthetic_environment("test")
    environment[missing_name] = "registry.example/nex/image:latest"
    with pytest.raises(EnvironmentCompositionError, match="immutable digest"):
        resolve_environment_composition("test", environ=environment)

    environment = smoke._synthetic_environment("test")
    values = list(ARTIFACT_REFERENCE_ENVIRONMENTS.values())
    environment[values[1]] = environment[values[0]]
    with pytest.raises(EnvironmentCompositionError, match="must be unique"):
        resolve_environment_composition("test", environ=environment)


def test_definition_validation_reports_unsafe_and_incomplete_compositions() -> None:
    development, test, staging, production = DEFAULT_ENVIRONMENT_COMPOSITIONS
    unknown = replace(
        development,
        environment_class="unknown",
        runtime_profiles=(),
        artifact_reference_policy="mutable_tag",
        admitted_background_profiles=("production",),
        production_contact_allowed=True,
    )
    duplicate_development = replace(test, environment_class="development")
    unsafe_test = replace(
        test,
        immutable_artifacts_required=False,
        allow_loopback=True,
        allow_local_storage=True,
    )
    unsafe_production = replace(production, production_contact_allowed=True)

    with pytest.raises(EnvironmentCompositionError) as raised:
        validate_environment_compositions(
            (
                development,
                unknown,
                duplicate_development,
                unsafe_test,
                staging,
                unsafe_production,
            )
        )

    detail = str(raised.value)
    assert "unknown environment class" in detail
    assert "duplicate environment class" in detail
    assert "invalid artifact reference policy" in detail
    assert "environment profiles are empty" in detail
    assert "invalid background profile admission" in detail
    assert "production contact is not approved" in detail
    assert "environment class coverage is incomplete" in detail
    assert "runtime profile coverage must be exact" in detail
    assert "protected class policy is unsafe" in detail


def test_manifest_loader_rejects_missing_invalid_and_drifted_documents(
    tmp_path: Path,
) -> None:
    with pytest.raises(EnvironmentCompositionError, match="unreadable"):
        load_environment_compositions(tmp_path)

    target = tmp_path / "deployment" / "environments"
    target.mkdir(parents=True)
    for name in ("development", "test", "staging", "production"):
        (target / f"{name}.yaml").write_text("[]\n", encoding="utf-8")
    with pytest.raises(EnvironmentCompositionError, match="not an object"):
        load_environment_compositions(tmp_path)

    (target / "development.yaml").write_text(
        "schema_version: wrong\n", encoding="utf-8"
    )
    with pytest.raises(EnvironmentCompositionError, match="schema drift"):
        load_environment_compositions(tmp_path)

    (target / "development.yaml").write_text(
        "schema_version: environment_composition.v1\n"
        "environment_class: development\n",
        encoding="utf-8",
    )
    with pytest.raises(EnvironmentCompositionError, match="field is invalid"):
        load_environment_compositions(tmp_path)

    for name in ("development", "test", "staging", "production"):
        source = ROOT / "deployment" / "environments" / f"{name}.yaml"
        (target / f"{name}.yaml").write_text(source.read_text(), encoding="utf-8")
    development = target / "development.yaml"
    development.write_text(
        development.read_text().replace("allow_loopback: true", 'allow_loopback: "true"'),
        encoding="utf-8",
    )
    with pytest.raises(EnvironmentCompositionError, match="field is invalid"):
        load_environment_compositions(tmp_path)

    development.write_text(
        (ROOT / "deployment" / "environments" / "development.yaml")
        .read_text()
        .replace("secret_source: local_environment", "secret_source: changed"),
        encoding="utf-8",
    )
    with pytest.raises(EnvironmentCompositionError, match="manifest drift"):
        load_environment_compositions(tmp_path)


def test_low_level_validation_helpers_cover_failure_branches() -> None:
    assert _required_bool(True, "flag") is True
    with pytest.raises(TypeError, match="boolean"):
        _required_bool("true", "flag")
    assert _required_string_sequence(["a", "b"], "names") == ("a", "b")
    for value in ("a", ["a", ""], ["a", 1]):
        with pytest.raises(TypeError, match="string list"):
            _required_string_sequence(value, "names")

    digest = "a" * 64
    assert _validated_image_reference(
        f"registry.example/nex/runtime@sha256:{digest}"
    ).endswith(digest)
    for reference in ("latest", "registry.example/runtime@sha256:bad"):
        with pytest.raises(EnvironmentCompositionError, match="immutable digest"):
            _validated_image_reference(reference)

    invalid = replace(
        resolve_environment_composition("local_mock", environ={}), status="UNKNOWN"
    )
    with pytest.raises(EnvironmentCompositionError, match="status"):
        environment_composition_projection(invalid)

    assert required_environment_names_for_composition("local_mock") == ()
    with pytest.raises(RuntimeProfileError, match="unsupported"):
        required_environment_names_for_composition("unknown")
