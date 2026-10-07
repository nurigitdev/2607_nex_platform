from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.production_api_key_custody import (
    PROVIDER_API_KEY_ENV_NAMES,
    ProductionApiKeyCustodyError,
    admit_production_api_key_custody,
    production_api_key_custody_projection,
    redact_sensitive_runtime_data,
)
from nex_runtime.production_secret_materialization import materialize_production_secrets
from run_platform_production_secret_materialization import _DeterministicSecretResolver
from run_platform_production_startup_admission import _synthetic_environment


ROOT = Path(__file__).resolve().parents[1]


def materialization():
    return materialize_production_secrets(
        _synthetic_environment(ROOT), _DeterministicSecretResolver(), root=ROOT
    )


def test_admits_exact_mo_only_provider_key_custody() -> None:
    custody = admit_production_api_key_custody(materialization())
    projection = production_api_key_custody_projection(custody)
    assert projection["owner"] == "nex-mo"
    assert projection["provider_api_key_environment_names"] == list(
        PROVIDER_API_KEY_ENV_NAMES
    )
    assert projection["configured_key_count"] == 3
    assert projection["raw_api_key_values_included"] is False


def test_rejects_missing_mo_environment_or_key_and_cross_owner_exposure() -> None:
    source = materialization()
    without_mo = replace(
        source,
        owner_environments=tuple(
            item for item in source.owner_environments if item.owner != "nex-mo"
        ),
    )
    with pytest.raises(ProductionApiKeyCustodyError, match="environment is missing"):
        admit_production_api_key_custody(without_mo)
    mo = next(item for item in source.owner_environments if item.owner == "nex-mo")
    incomplete = replace(
        source,
        owner_environments=tuple(
            replace(item, secrets=item.secrets[:-1]) if item.owner == "nex-mo" else item
            for item in source.owner_environments
        ),
    )
    with pytest.raises(ProductionApiKeyCustodyError, match="incomplete"):
        admit_production_api_key_custody(incomplete)
    provider_secret = next(
        item for item in mo.secrets if item.target_environment_name in PROVIDER_API_KEY_ENV_NAMES
    )
    contaminated = replace(
        source,
        owner_environments=tuple(
            replace(item, secrets=(*item.secrets, provider_secret))
            if item.owner == "nex-oa"
            else item
            for item in source.owner_environments
        ),
    )
    with pytest.raises(ProductionApiKeyCustodyError, match="escaped"):
        admit_production_api_key_custody(contaminated)


def test_recursive_redactor_handles_keys_values_bearer_sequences_and_scalars() -> None:
    value = {
        "Authorization": "Bearer top-secret",
        "safe": ["prefix top-secret suffix", 3, True],
        "nested": ("visible", {"api-key": "other"}),
    }
    assert redact_sensitive_runtime_data(
        value, sensitive_values=("", "top-secret", 3)
    ) == {
        "Authorization": "<redacted>",
        "safe": ["prefix <redacted> suffix", 3, True],
        "nested": ("visible", {"api-key": "<redacted>"}),
    }
    assert redact_sensitive_runtime_data("Bearer abc") == "Bearer <redacted>"


def test_projection_rejects_invalid_custody() -> None:
    custody = admit_production_api_key_custody(materialization())
    with pytest.raises(ProductionApiKeyCustodyError, match="projection is invalid"):
        production_api_key_custody_projection(replace(custody, status="OTHER"))
