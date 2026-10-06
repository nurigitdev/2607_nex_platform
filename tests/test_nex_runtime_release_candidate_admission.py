from __future__ import annotations

from copy import deepcopy
import json

import pytest

from nex_runtime.release_candidate_admission import (
    EXPECTED_BROWSER_VIEWPORTS,
    RELEASE_CANDIDATE_ADMISSION_SCHEMA_VERSION,
    RELEASE_CANDIDATE_PROVIDER_ADMISSIONS,
    evaluate_release_candidate_admission,
)
import run_platform_release_candidate_admission as runner


def _env() -> dict[str, str]:
    return runner.build_sample_release_candidate_environment()


def test_valid_test_live_profile_is_admitted_without_execution() -> None:
    result = evaluate_release_candidate_admission(_env())

    assert result["admission_schema_version"] == (
        RELEASE_CANDIDATE_ADMISSION_SCHEMA_VERSION
    )
    assert result["status"] == "PASS"
    assert result["admitted"] is True
    assert result["failed_checks"] == []
    assert result["issues"] == []
    assert result["database_profile"]["service_count"] == 5
    assert [
        item["expected_database_name"]
        for item in result["database_profile"]["targets"]
    ] == [
        "nex_oa_test",
        "nex_mo_test",
        "nex_cx_test",
        "nex_ae_test",
        "nex_ag_test",
    ]
    assert result["provider_profile"]["capability_count"] == 3
    assert result["browser_profile"]["viewport_count"] == 2
    assert result["actual_execution"] == {
        "postgresql": False,
        "remote_provider": False,
        "browser": False,
    }
    assert result["decision"] == {
        "protected_execution_admitted": True,
        "next_slice": "1396",
    }


def test_admission_is_model_independent() -> None:
    env = _env()
    env.update(
        {
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "future-embedding-model",
            "NEX_MO_REMOTE_RERANKER_MODEL": "future-reranker-model",
            "NEX_MO_VLLM_MODEL": "future-generation-model",
        }
    )

    result = evaluate_release_candidate_admission(env)
    serialized = json.dumps(result, sort_keys=True)

    assert result["status"] == "PASS"
    assert result["checks"]["provider_admission_model_independent"] is True
    assert "future-embedding-model" not in serialized
    assert "future-reranker-model" not in serialized
    assert "future-generation-model" not in serialized
    assert [
        item["alias"] for item in result["provider_profile"]["capabilities"]
    ] == [item.alias for item in RELEASE_CANDIDATE_PROVIDER_ADMISSIONS]


def test_disabled_and_wrong_profile_fail_before_configuration() -> None:
    disabled = evaluate_release_candidate_admission({})
    wrong_profile_env = _env()
    wrong_profile_env["NEX_S140_RELEASE_CANDIDATE_PROFILE"] = "production"
    wrong_profile = evaluate_release_candidate_admission(wrong_profile_env)

    assert disabled["status"] == "SKIPPED"
    assert disabled["failure_code"] == "release_candidate_admission_not_enabled"
    assert wrong_profile["status"] == "FAIL"
    assert wrong_profile["failure_code"] == "release_candidate_profile_not_allowed"
    assert wrong_profile["actual_execution"]["postgresql"] is False


@pytest.mark.parametrize(
    ("name", "value", "issue"),
    [
        (
            "NEX_PERSISTENCE_MODE",
            "memory",
            "mode_invalid:NEX_PERSISTENCE_MODE",
        ),
        (
            "NEX_MO_PROVIDER_MODE",
            "mock",
            "mode_invalid:NEX_MO_PROVIDER_MODE",
        ),
        (
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE",
            "TEST_MOCK",
            "mode_invalid:NEX_SERVICE_TOKEN_ROLLOUT_PROFILE",
        ),
        (
            "NEX_AG_OPERATIONS_SOURCE_MODE",
            "database",
            "mode_invalid:NEX_AG_OPERATIONS_SOURCE_MODE",
        ),
        (
            "NEX_AE_AUTH_SESSION_MODE",
            "mock",
            "mode_invalid:NEX_AE_AUTH_SESSION_MODE",
        ),
        (
            "NEX_MO_PROTECTED_LIVE_PROFILE",
            "dgx_pcx_legacy",
            "canonical_provider_profile_required",
        ),
        (
            "NEX_MO_REMOTE_EMBEDDING_URL",
            "not-a-url",
            "provider_endpoint_invalid:embedding",
        ),
        (
            "NEX_MO_REMOTE_RERANKER_URL",
            "",
            "provider_endpoint_invalid:reranking",
        ),
        (
            "NEX_MO_VLLM_BASE_URL",
            "ftp://provider.invalid",
            "provider_endpoint_invalid:generation",
        ),
        (
            "NEX_S140_BROWSER_VIEWPORTS",
            "desktop",
            "browser_viewport_inventory_invalid",
        ),
        (
            "NEX_S140_BROWSER_VIEWPORTS",
            "desktop,desktop",
            "browser_viewport_inventory_invalid",
        ),
    ],
)
def test_configuration_drift_is_rejected(
    name: str,
    value: str,
    issue: str,
) -> None:
    env = _env()
    env[name] = value

    result = evaluate_release_candidate_admission(env)

    assert result["status"] == "FAIL"
    assert result["admitted"] is False
    assert issue in result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_reversed_exact_viewport_inventory_is_admitted() -> None:
    env = _env()
    env["NEX_S140_BROWSER_VIEWPORTS"] = "mobile,desktop"

    result = evaluate_release_candidate_admission(env)

    assert result["status"] == "PASS"
    assert result["browser_profile"]["configured_viewports"] == [
        "mobile",
        "desktop",
    ]
    assert result["browser_profile"]["viewports"] == [
        {"name": name, **dimensions}
        for name, dimensions in EXPECTED_BROWSER_VIEWPORTS.items()
    ]


@pytest.mark.parametrize(
    ("name", "value", "issue"),
    [
        ("NEX_OA_TEST_DATABASE_URL", "", "test_database_url_missing_or_placeholder"),
        (
            "NEX_CX_TEST_DATABASE_URL",
            "sqlite:///nex_cx_test.db",
            "test_database_url_invalid",
        ),
        (
            "NEX_AG_TEST_DATABASE_URL",
            "postgresql+psycopg://nex_ag_user:x@localhost/nex_ag_dev",
            "test_database_name_mismatch",
        ),
        (
            "NEX_MO_TEST_DATABASE_URL",
            "postgresql+psycopg://wrong_user:x@localhost/nex_mo_test",
            "test_database_role_mismatch",
        ),
    ],
)
def test_database_target_drift_is_rejected(
    name: str,
    value: str,
    issue: str,
) -> None:
    env = _env()
    env[name] = value

    result = evaluate_release_candidate_admission(env)

    assert result["status"] == "FAIL"
    assert issue in result["issues"]
    assert result["database_profile"]["service_count"] == 0


def test_duplicate_service_database_urls_are_rejected() -> None:
    env = _env()
    env["NEX_AG_TEST_DATABASE_URL"] = env["NEX_AE_TEST_DATABASE_URL"]

    result = evaluate_release_candidate_admission(env)

    assert result["status"] == "FAIL"
    assert "test_database_name_mismatch" in result["issues"]


def test_sensitive_configuration_values_are_not_projected() -> None:
    env = _env()
    env["NEX_MO_VLLM_API_KEY"] = "private-s140-api-key"
    result = evaluate_release_candidate_admission(env)
    serialized = json.dumps(result, sort_keys=True)

    assert "private-s140-api-key" not in serialized
    assert "contract-only" not in serialized
    assert "provider.invalid" not in serialized
    assert result["redaction"]["status"] == "PASS"


def test_sensitive_value_assertion_rejects_accidental_projection() -> None:
    env = _env()
    env["NEX_TEST_SECRET"] = "private-s140-secret"

    with pytest.raises(ValueError, match="contains sensitive values"):
        from nex_runtime.release_candidate_admission import (
            _assert_sensitive_values_absent,
        )

        _assert_sensitive_values_absent(
            {"leak": "private-s140-secret"},
            env,
        )


def test_runner_sample_and_disabled_modes(capsys, monkeypatch) -> None:
    sample = runner.run_platform_release_candidate_admission(
        contract_sample=True
    )
    disabled = runner.run_platform_release_candidate_admission({})

    assert sample["status"] == "PASS"
    assert sample["contract_sample"] is True
    assert runner.summary_line(sample) == (
        "platform_release_candidate_admission=pass databases=5 "
        "providers=3 viewports=2 next=1396"
    )
    assert disabled["status"] == "SKIPPED"
    assert "admitted=false" in runner.summary_line(disabled)

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_admission",
        lambda **_: sample,
    )
    assert runner.main(["--sample", "--summary"]) == 0
    assert "databases=5" in capsys.readouterr().out
    assert runner.main(["--sample"]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failed = deepcopy(sample)
    failed["status"] = "FAIL"
    failed["admitted"] = False
    failed["decision"]["next_slice"] = "blocked"
    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_admission",
        lambda **_: failed,
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out


def test_url_validation_rejects_non_strings_and_hostless_urls() -> None:
    from nex_runtime.release_candidate_admission import (
        _configured_viewports,
        _valid_http_url,
    )

    assert _valid_http_url("https://provider.invalid") is True
    assert _valid_http_url(None) is False
    assert _valid_http_url(123) is False
    assert _valid_http_url("http://") is False
    assert _configured_viewports(None) == ()
