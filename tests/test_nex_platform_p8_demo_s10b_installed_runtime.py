from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
import run_p8_demo_s10b_installed_runtime as smoke
from nex_runtime import DEFAULT_SERVICE_SCOPE


def _database_environment() -> dict[str, str]:
    return {
        name: f"postgresql+psycopg://{role}:secret@127.0.0.1:5432/{database}"
        for name, role, database in smoke.DATABASES.values()
    }


def test_protected_smoke_is_explicitly_opt_in() -> None:
    result = smoke.run_p8_demo_s10b_installed_runtime({}, execute=False)

    assert result == {
        "schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"--execute and {smoke.SMOKE_ENV}=1 are required",
    }
    assert smoke.summary_line(result).endswith("checks=0/0")


def test_database_admission_requires_exact_test_database_and_owner() -> None:
    environment = _database_environment()

    admitted = smoke._database_urls(environment)

    assert set(admitted) == set(smoke.DATABASES)
    environment["NEX_AE_TEST_DATABASE_URL"] = (
        "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_dev"
    )
    with pytest.raises(smoke.P8DemoS10BSmokeError, match="nex_ae_test"):
        smoke._database_urls(environment)


def test_smoke_authority_issues_signed_only_service_token() -> None:
    authority = smoke._SignedAuthority()
    runtime = authority.admission("nex-wc")

    claims = runtime.admit(
        "Bearer " + authority.token("nex-ae-api", "nex-wc"),
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
        route_class="WRITE",
    )

    assert claims.service_id == "nex-ae-api"
    assert claims.token_kind == "SIGNED"
    assert runtime.public_snapshot()["admission_counts"] == {
        "accepted_mock": 0,
        "accepted_signed": 1,
        "rejected": 0,
        "introspected": 1,
    }


@dataclass(frozen=True)
class _FrozenFailure(Exception):
    detail: str


def test_temporary_environment_restores_values_for_frozen_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_P8_DEMO_S10B_EXISTING", "before")
    monkeypatch.delenv("NEX_P8_DEMO_S10B_ADDED", raising=False)

    with (
        pytest.raises(_FrozenFailure),
        smoke._temporary_environ(
            {
                "NEX_P8_DEMO_S10B_EXISTING": "during",
                "NEX_P8_DEMO_S10B_ADDED": "during",
            }
        ),
    ):
        assert os.environ["NEX_P8_DEMO_S10B_EXISTING"] == "during"
        raise _FrozenFailure("expected")

    assert os.environ["NEX_P8_DEMO_S10B_EXISTING"] == "before"
    assert "NEX_P8_DEMO_S10B_ADDED" not in os.environ
