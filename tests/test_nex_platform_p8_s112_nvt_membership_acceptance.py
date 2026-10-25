from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke/run_p8_s112_nvt_membership_acceptance.py"
SPEC = importlib.util.spec_from_file_location("p8_s112_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _env() -> dict[str, str]:
    return {
        MODULE.SMOKE_ENV: "1",
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1:5432/nex_oa_test"
        ),
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_WC_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_wc_user:secret@127.0.0.1:5432/nex_wc_test"
        ),
        "NEX_EOS_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_eos_user:secret@127.0.0.1:5432/nex_eos_test"
        ),
    }


def _backend() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "model_profile": "general-llm-default",
        "model_ref": "model-revision",
        "live_generation_stages": ["INTENT", "INTENT"],
        "nvt_intent_label": "PROJECT.NVT_PROJECT.CREATE",
        "membership_intent_label": "PROJECT.MEMBERSHIP.ADD_MANY",
        "nvt_crud_verified": True,
        "oa_batch_resolution_verified": True,
        "wc_approval_verified": True,
        "eos_exact_replay_verified": True,
        "residue_count": 0,
        "project_membership_batch_result": {
            "overall_status": "PARTIALLY_APPLIED",
            "summary": {"requested_count": 3, "applied_count": 1},
        },
    }


class Migration:
    planned = ("one",)
    applied = ()
    skipped = ("one",)


def test_protected_acceptance_is_skipped_by_default() -> None:
    result = MODULE.run_p8_s112_nvt_membership_acceptance({}, execute=False)

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False


def test_acceptance_composes_backend_browser_and_redacted_evidence(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "run_service_migrations", lambda *_args, **_kwargs: Migration())
    monkeypatch.setattr(
        MODULE.browser_smoke,
        "prepare_playwright_postgres_smoke",
        lambda *_args, **_kwargs: type("Prepared", (), {"ae_app": object()})(),
    )
    monkeypatch.setattr(MODULE, "_register_browser_routes", lambda *_args, **_kwargs: None)

    def browser_runner(_env, **kwargs):
        kwargs["prepare_runner"]({}, "test")
        return {
            "status": "PASS",
            "source_smokes": {"node_playwright": {"status": "PASS"}},
            "cleanup_observations": {"remaining": 0},
        }

    result = MODULE.run_p8_s112_nvt_membership_acceptance(
        _env(),
        execute=True,
        journey_runner=lambda *_args: _backend(),
        browser_runner=browser_runner,
    )

    assert result["status"] == "PASS"
    assert result["checks_passed"] == result["checks_total"]
    assert result["result_summary"]["requested_count"] == 3
    serialized = str(result)
    assert "secret" not in serialized
    assert "127.0.0.1" not in serialized


def test_invalid_database_or_backend_failure_is_fail_closed(monkeypatch) -> None:
    bad = MODULE.run_p8_s112_nvt_membership_acceptance(
        {**_env(), "NEX_EOS_TEST_DATABASE_URL": "sqlite:///tmp.db"},
        execute=True,
    )
    assert bad["status"] == "FAIL"

    monkeypatch.setattr(MODULE, "run_service_migrations", lambda *_args, **_kwargs: Migration())
    failed = MODULE.run_p8_s112_nvt_membership_acceptance(
        _env(),
        execute=True,
        journey_runner=lambda *_args: {"status": "FAIL"},
        browser_runner=lambda *_args, **_kwargs: {},
    )
    assert failed["status"] == "FAIL"


def test_summary_reports_all_execution_boundaries() -> None:
    line = MODULE.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "actual_playwright": True,
            "checks": {"a": True, "b": True},
        }
    )
    assert "postgres=true" in line
    assert "provider=true" in line
    assert "playwright=true" in line
    assert "checks=2/2" in line
