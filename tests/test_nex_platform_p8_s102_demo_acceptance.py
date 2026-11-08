from __future__ import annotations

from contextlib import contextmanager
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s102_demo_acceptance as smoke


def _database_env() -> dict[str, str]:
    return {
        smoke.p8_s66.p8_s65.AE_DATABASE_ENV: (
            "postgresql+psycopg://nex_ae_user:private@localhost/nex_ae_test"
        ),
        smoke.p8_s66.p8_s65.WC_DATABASE_ENV: (
            "postgresql+psycopg://nex_wc_user:private@localhost/nex_wc_test"
        ),
        smoke.p8_s66.p8_s65.OA_DATABASE_ENV: (
            "postgresql+psycopg://nex_oa_user:private@localhost/nex_oa_test"
        ),
        smoke.p8_s66.EOS_DATABASE_ENV: (
            "postgresql+psycopg://nex_eos_user:private@localhost/nex_eos_test"
        ),
    }


def _backend_evidence() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "actual_remote_provider": True,
        "s65": {"status": "PASS", "model_ref": "model-revision"},
        "commit_state": "COMMITTED",
        "verification_status": "VERIFIED",
        "voucher_ref": {"type": "eos.voucher_draft", "id": "voucher-s102"},
        "checks": {"voucher_get_list_membership_filtered": True},
        "residue_count": 0,
    }


def test_s102_gate_is_explicitly_protected() -> None:
    assert smoke.run_p8_s102_demo_acceptance({}, execute=False)["status"] == "SKIPPED"
    assert smoke.run_p8_s102_demo_acceptance({}, execute=True)["status"] == "SKIPPED"


def test_s102_rejects_non_test_database_target_without_leaking_url() -> None:
    env = {**_database_env(), smoke.SMOKE_ENV: "1"}
    env[smoke.p8_s66.EOS_DATABASE_ENV] = (
        "postgresql+psycopg://nex_eos_user:private@localhost/nex_eos_dev"
    )

    result = smoke.run_p8_s102_demo_acceptance(env, execute=True)

    assert result["status"] == "FAIL"
    assert result["actual_postgres"] is False
    assert "private" not in str(result)
    assert "nex_eos_dev" not in str(result)


def test_s102_composes_backend_and_browser_evidence() -> None:
    def browser_runner(_env, *, prepare_runner, node_runner):
        assert callable(prepare_runner)
        assert callable(node_runner)
        return {
            "status": "PASS",
            "source_smokes": {"node_playwright": {"status": "PASS"}},
            "browser_observations": {
                "prompt_submitted": True,
                "committed_result_visible": True,
            },
        }

    result = smoke.run_p8_s102_demo_acceptance(
        {**_database_env(), smoke.SMOKE_ENV: "1"},
        execute=True,
        backend_runner=lambda *_args, **_kwargs: _backend_evidence(),
        browser_runner=browser_runner,
    )

    assert result["status"] == "PASS"
    assert result["checks_passed"] == result["checks_total"] == 8
    assert result["backend"]["commit_state"] == "COMMITTED"
    assert result["browser"]["node_status"] == "PASS"


def test_s102_binds_default_backend_to_immutable_v021_release(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    locked_source = Path("/tmp/p8-s102-locked-nsl")

    def backend_runner(_env, **kwargs):
        captured.update(kwargs)
        return _backend_evidence()

    @contextmanager
    def locked_source_context(_env):
        yield locked_source

    monkeypatch.setattr(
        smoke.p8_s66,
        "run_p8_s66_golden_a_eos_commit_journey",
        backend_runner,
    )
    monkeypatch.setattr(smoke, "_locked_nsl_v021_source", locked_source_context)

    result = smoke._run_protected_backend(
        _database_env(),
        backend_runner=backend_runner,
    )

    assert result["status"] == "PASS"
    assert captured == {
        "execute": True,
        "source": locked_source,
        "lock_path": smoke.V021_LOCK,
        "wheel_directory": smoke.V021_WHEEL_DIRECTORY,
    }


def test_demo_projection_requires_session_and_exact_prompt() -> None:
    fixture = smoke.load_golden_a_fixture()
    app = FastAPI()
    smoke._register_demo_projection_routes(
        app,
        assistant_text="PROJECT-A-2 프로젝트에 84,000원 전표가 등록되었습니다.",
        fixture=fixture,
        backend=_backend_evidence(),
    )
    client = TestClient(app)
    payload = {
        "interaction_id": "browser-generated-id",
        "workspace_id": "workspace-s102",
        "chat_document_id": "chat-s102",
        "user_message": fixture["scenario"]["prompt"],
    }

    assert client.post("/api/v1/chat/interactions", json=payload).status_code == 401
    client.cookies.set("nex_session", "opaque-test-cookie")
    mismatch = client.post(
        "/api/v1/chat/interactions",
        json={**payload, "user_message": "different prompt"},
    )
    assert mismatch.status_code == 422

    admitted = client.post("/api/v1/chat/interactions", json=payload)
    assert admitted.status_code == 200
    interaction_id = admitted.json()["interaction_id"]
    progress = client.get(f"/api/v1/chat/interactions/{interaction_id}/progress")
    refresh = client.post(f"/api/v1/chat/interactions/{interaction_id}/refresh")
    response = client.get(f"/api/v1/chat/interactions/{interaction_id}/response")
    quality = client.get(f"/api/v1/chat/interactions/{interaction_id}/citation-quality")

    assert progress.json()["terminal"] is True
    assert refresh.json()["interaction"]["status"] == "COMPLETED"
    assert "84,000원" in response.json()["content"]
    assert quality.json()["workflow_status"] == "NOT_REQUIRED"
