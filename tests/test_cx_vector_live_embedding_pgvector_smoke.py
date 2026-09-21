from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "scripts" / "smoke" / "run_cx_vector_live_embedding_pgvector_smoke.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "cx_vector_live_embedding_pgvector_smoke",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_env(module, **overrides: str) -> dict[str, str]:
    return {
        module.SMOKE_ENV: "1",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.test/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "test-secret",
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-Embedding-4B",
        **overrides,
    }


def test_smoke_activation_profile_configuration_and_target_guards(monkeypatch):
    module = _module()
    assert module.run_cx_vector_live_embedding_pgvector_smoke({})["status"] == "SKIPPED"
    assert module.run_cx_vector_live_embedding_pgvector_smoke(
        _live_env(module, **{module.PROFILE_ENV: "dev"})
    )["error"]["code"] == "profile_not_allowed"

    no_endpoint = _live_env(module)
    no_endpoint["NEX_MO_REMOTE_EMBEDDING_URL"] = ""
    no_endpoint["NEX_MO_REMOTE_EMBEDDING_API_KEY"] = ""
    issues = module.run_cx_vector_live_embedding_pgvector_smoke(no_endpoint)
    assert issues["error"]["code"] == "configuration_invalid"
    assert {item["error_code"] for item in issues["error"]["detail"]} == {
        "remote_embedding_endpoint_not_configured",
        "remote_embedding_authorization_not_configured",
    }

    monkeypatch.setattr(module, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_a, **_k: "postgresql://wrong@localhost/wrong",
    )
    target = module.run_cx_vector_live_embedding_pgvector_smoke(_live_env(module))
    assert target["error"]["code"] == "target_not_allowed"


def test_configuration_rejects_shape_model_and_timeout():
    module = _module()
    shape = module.remote_embedding_configuration_issues(
        _live_env(module, NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE="legacy")
    )
    assert shape[0]["error_code"] == "remote_embedding_request_shape_mismatch"
    model = module.remote_embedding_configuration_issues(
        _live_env(module, NEX_MO_REMOTE_EMBEDDING_MODEL="Unexpected")
    )
    assert model[0]["error_code"] == "remote_embedding_model_mismatch"
    timeout = module.remote_embedding_configuration_issues(
        _live_env(module, NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS="slow")
    )
    assert timeout == [{"error_code": "remote_embedding_timeout_invalid"}]


def test_request_live_embedding_uses_compatible_shape_and_safe_summary():
    module = _module()
    calls: list[dict[str, object]] = []

    class Response:
        status_code = 200
        is_error = False

        def json(self):
            return {
                "object": "list",
                "data": [
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [1.0] + [0.0] * (module.VECTOR_DIMENSION - 1),
                    }
                ],
            }

    def requester(method: str, url: str, **kwargs: object):
        calls.append({"method": method, "url": url, **kwargs})
        return Response()

    env = _live_env(module)
    vector, evidence = module.request_live_embedding(env, requester=requester)
    assert len(vector) == module.VECTOR_DIMENSION
    assert evidence["vector_dimension"] == module.VECTOR_DIMENSION
    assert evidence["finite"] is True
    assert evidence["non_zero"] is True
    assert calls[0]["json"] == {
        "model": "Qwen3-Embedding-4B",
        "input": [module.LIVE_INPUT],
    }
    assert calls[0]["headers"]["Authorization"] == "Bearer test-secret"
    assert "url" not in evidence["config"]
    assert "api_key" not in evidence["config"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"data": []}, "exactly one"),
        ({"data": [{}]}, "missing"),
        ({"data": [{"embedding": [1.0]}]}, "dimension"),
        (
            {"data": [{"embedding": [float("nan")] * 2560}]},
            "non-finite",
        ),
        ({"data": [{"embedding": [0.0] * 2560}]}, "all zero"),
    ],
)
def test_request_live_embedding_rejects_invalid_vectors(
    payload,
    message,
    monkeypatch,
):
    module = _module()

    monkeypatch.setattr(
        module,
        "execute_remote_embedding_request",
        lambda *_a, **_k: payload,
    )

    with pytest.raises(ValueError, match=message):
        module.request_live_embedding(_live_env(module))


def test_smoke_success_failure_exception_redaction_summary_and_main(
    monkeypatch,
    capsys,
):
    module = _module()
    url = "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
    monkeypatch.setattr(module, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(module, "service_database_url", lambda *_a, **_k: url)
    monkeypatch.setattr(
        module,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(applied=(), skipped=("existing",)),
    )
    execution = {
        "failed_checks": [],
        "check_count": 1,
        "provider": {"vector_dimension": 2560},
    }
    monkeypatch.setattr(module, "_execute_smoke", lambda *_a, **_k: execution)
    passing = module.run_cx_vector_live_embedding_pgvector_smoke(_live_env(module))
    assert passing["status"] == "PASS"
    assert passing["remote_embedding_required"] is True
    assert passing["migration"]["skipped"] == ["existing"]

    monkeypatch.setattr(
        module,
        "_execute_smoke",
        lambda *_a, **_k: {"failed_checks": ["retrieval"]},
    )
    assert module.run_cx_vector_live_embedding_pgvector_smoke(
        _live_env(module)
    )["error"]["code"] == "live_embedding_pgvector_smoke_failed"

    monkeypatch.setattr(
        module,
        "run_service_migrations",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    failed = module.run_cx_vector_live_embedding_pgvector_smoke(_live_env(module))
    assert failed["error"] == {"code": "execution_failed", "detail": "RuntimeError"}

    assert module._target_url_allowed(url)
    assert not module._target_url_allowed(url.replace("test", "dev"))
    module.assert_evidence_redacted({"safe": True}, _live_env(module))
    with pytest.raises(ValueError, match="not redacted"):
        module.assert_evidence_redacted(
            {"leak": "test-secret"},
            _live_env(module),
        )
    assert "skipped" in module._summary({"status": "SKIPPED"})
    assert "checks=2/2" in module._summary(
        {
            "status": "PASS",
            "check_count": 2,
            "provider": {"vector_dimension": 2560},
        }
    )
    assert "error=boom" in module._summary(
        {"status": "FAIL", "error": {"code": "boom"}}
    )
    monkeypatch.setattr(
        module,
        "run_cx_vector_live_embedding_pgvector_smoke",
        lambda: {"status": "SKIPPED"},
    )
    assert module.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(
        module,
        "run_cx_vector_live_embedding_pgvector_smoke",
        lambda: {"status": "FAIL", "error": {"code": "boom"}},
    )
    assert module.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
