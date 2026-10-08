from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.production_startup_admission import (
    PRODUCTION_STARTUP_ADMISSION_SCHEMA_VERSION,
    ProductionStartupAdmissionError,
    _configuration_digest,
    _is_placeholder,
    _valid_https_endpoint,
    _valid_versioned_reference,
    admit_external_startup,
    admit_production_startup,
    external_startup_admission_projection,
    production_startup_admission_projection,
)
from nex_runtime.runtime_profiles import runtime_profile_environment_overlay

import run_platform_production_startup_admission as smoke


ROOT = Path(__file__).resolve().parents[1]


def test_valid_production_prestart_is_metadata_only_and_deterministic() -> None:
    environment = smoke._synthetic_environment()
    first = admit_production_startup(environment, root=ROOT)
    second = admit_production_startup(dict(reversed(tuple(environment.items()))), root=ROOT)
    projection = production_startup_admission_projection(first)

    assert first == second
    assert first.schema_version == PRODUCTION_STARTUP_ADMISSION_SCHEMA_VERSION
    assert projection["status"] == "ADMITTED_FOR_SECRET_MATERIALIZATION"
    assert projection["secret_reference_count"] == 20
    assert projection["public_connection_count"] == 11
    assert projection["control_environment_count"] == 6
    assert projection["https_endpoint_count"] == 11
    assert projection["raw_secret_environment_count"] == 0
    assert projection["raw_secret_values_included"] is False
    assert projection["reference_values_included"] is False
    assert projection["endpoint_values_included"] is False
    assert "external/nex-platform" not in str(projection)


def test_staging_live_external_admission_reuses_fail_closed_boundary() -> None:
    environment = smoke._synthetic_environment()
    environment.update(runtime_profile_environment_overlay("staging_live"))
    admission = admit_external_startup(
        environment,
        profile="staging_live",
        root=ROOT,
    )
    projection = external_startup_admission_projection(
        admission,
        expected_profile="staging_live",
    )

    assert projection["profile"] == "staging_live"
    assert projection["secret_reference_count"] == 20
    with pytest.raises(ProductionStartupAdmissionError, match="projection"):
        external_startup_admission_projection(
            admission,
            expected_profile="production",
        )
    with pytest.raises(ProductionStartupAdmissionError, match="profile"):
        admit_external_startup(environment, profile="test", root=ROOT)
    with pytest.raises(ProductionStartupAdmissionError, match="profile"):
        external_startup_admission_projection(
            admission,
            expected_profile="test",
        )
    production = admit_production_startup(smoke._synthetic_environment(), root=ROOT)
    assert external_startup_admission_projection(
        production,
        expected_profile="production",
    )["profile"] == "production"
    with pytest.raises(ProductionStartupAdmissionError, match="projection"):
        external_startup_admission_projection(
            replace(admission, secret_reference_count=0),
            expected_profile="staging_live",
        )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("NEX_PROFILE", "staging_live", "runtime mode is invalid"),
        ("NEX_OA_DATABASE_URL_REF", "", "secret reference"),
        ("NEX_OA_DATABASE_URL_REF", "secret://external/path", "secret reference"),
        ("NEX_OA_DATABASE_URL", "raw-value", "raw secret deployment input"),
        ("NEX_OA_BASE_URL", "http://oa.example", "HTTPS endpoint"),
        ("NEX_OA_BASE_URL", "https://127.0.0.1", "HTTPS endpoint"),
        ("NEX_CONFIG_GENERATION", "bad", "generation"),
        ("NEX_TLS_CERTIFICATE_REF", "secret://wrong/path@v1", "TLS reference"),
    ),
)
def test_admission_fails_closed_without_echoing_values(
    name: str, value: str, message: str
) -> None:
    environment = smoke._synthetic_environment()
    environment[name] = value

    with pytest.raises(ProductionStartupAdmissionError, match=message) as raised:
        admit_production_startup(environment, root=ROOT)

    assert value not in str(raised.value) or value == ""
    assert name in str(raised.value)


def test_projection_rejects_every_invalid_admission_field() -> None:
    admission = admit_production_startup(smoke._synthetic_environment(), root=ROOT)
    invalid_values = (
        replace(admission, schema_version="wrong"),
        replace(admission, profile="test"),
        replace(admission, status="DENIED"),
        replace(admission, configuration_digest="bad"),
        replace(admission, secret_reference_count=0),
        replace(admission, public_connection_count=0),
        replace(admission, control_environment_count=0),
        replace(admission, https_endpoint_count=0),
        replace(admission, raw_secret_environment_count=1),
    )
    for invalid in invalid_values:
        with pytest.raises(ProductionStartupAdmissionError, match="projection"):
            production_startup_admission_projection(invalid)


def test_reference_endpoint_placeholder_and_digest_helpers_cover_edges() -> None:
    assert _valid_versioned_reference(
        "secret://provider/path/to/key@v2", scheme="secret"
    )
    for value in (
        "",
        "x" * 513,
        "changeme",
        "secret://provider/path @v1",
        "tls://provider/path@v1",
        "secret://user:pass@provider/path@v1",
        "secret://provider/path@v1?query=yes",
        "secret://provider/path@v1#fragment",
        "secret://provider/@v1",
        "secret://provider/path@",
    ):
        assert not _valid_versioned_reference(value, scheme="secret")

    assert _valid_https_endpoint("https://service.example/path")
    for value in (
        "",
        "x" * 2049,
        "<secret>",
        "https://service.example/a b",
        "http://service.example",
        "https://user:pass@service.example",
        "https://service.example?query=yes",
        "https://service.example#fragment",
        "https://localhost",
        "https://api.localhost",
        "https://127.0.0.1",
    ):
        assert not _valid_https_endpoint(value)

    assert _is_placeholder("CHANGE-ME")
    assert _is_placeholder("prefix<secret>suffix")
    assert not _is_placeholder("config:valid-generation")
    assert _configuration_digest([("b", "2"), ("a", "1")]) == (
        _configuration_digest([("a", "1"), ("b", "2")])
    )
