from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "smoke"
    / "run_cx_permission_hybrid_live_postgres_smoke.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_cx_permission_hybrid_live_postgres_smoke",
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
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-Embedding-4B",
        "NEX_MO_REMOTE_RERANKER_URL": "http://reranker.test/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
        "NEX_MO_REMOTE_RERANKER_MODEL": "Qwen3-Reranker-4B",
        "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": "Qwen3-Reranker-4B",
        **overrides,
    }


def test_activation_profile_configuration_and_database_guards(monkeypatch):
    module = _module()

    skipped = module.run_cx_permission_hybrid_live_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"

    profile = module.run_cx_permission_hybrid_live_postgres_smoke(
        _live_env(module, **{module.PROFILE_ENV: "dev"})
    )
    assert profile["error"]["code"] == "profile_not_allowed"

    missing = _live_env(module)
    missing.update(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "",
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "",
            "NEX_MO_REMOTE_RERANKER_URL": "",
            "NEX_MO_REMOTE_RERANKER_API_KEY": "",
        }
    )
    invalid = module.run_cx_permission_hybrid_live_postgres_smoke(missing)
    assert invalid["error"]["code"] == "configuration_invalid"
    assert {item["error_code"] for item in invalid["error"]["detail"]} == {
        "remote_embedding_endpoint_not_configured",
        "remote_embedding_authorization_not_configured",
        "remote_reranker_endpoint_not_configured",
        "remote_reranker_authorization_not_configured",
    }

    monkeypatch.setattr(module, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_a, **_k: "postgresql://wrong@localhost/wrong",
    )
    target = module.run_cx_permission_hybrid_live_postgres_smoke(
        _live_env(module)
    )
    assert target["error"]["code"] == "target_not_allowed"


def test_provider_configuration_rejects_shape_model_and_timeout():
    module = _module()
    issues = module.remote_provider_configuration_issues(
        _live_env(
            module,
            NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE="legacy",
            NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE="legacy",
            NEX_MO_REMOTE_EMBEDDING_MODEL="unexpected-embedding",
            NEX_MO_REMOTE_RERANKER_MODEL="unexpected-reranker",
        )
    )
    assert {item["error_code"] for item in issues} == {
        "remote_embedding_request_shape_mismatch",
        "remote_embedding_model_mismatch",
        "remote_reranker_request_shape_mismatch",
        "remote_reranker_model_mismatch",
    }

    timeout = module.remote_provider_configuration_issues(
        _live_env(module, NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS="slow")
    )
    assert timeout == [{"error_code": "remote_provider_timeout_invalid"}]


def test_live_embedding_batch_uses_safe_openai_compatible_request():
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
                        "index": 1,
                        "embedding": [2.0]
                        + [0.0] * (module.VECTOR_DIMENSION - 1),
                    },
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [1.0]
                        + [0.0] * (module.VECTOR_DIMENSION - 1),
                    },
                ],
            }

    def requester(method: str, url: str, **kwargs: object):
        calls.append({"method": method, "url": url, **kwargs})
        return Response()

    vectors, evidence = module.request_live_embeddings(
        _live_env(module),
        ["query", "chunk"],
        requester=requester,
    )

    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0
    assert evidence["response_count"] == 2
    assert evidence["vector_dimension"] == module.VECTOR_DIMENSION
    assert calls[0]["json"] == {
        "model": "Qwen3-Embedding-4B",
        "input": ["query", "chunk"],
    }
    assert calls[0]["headers"]["Authorization"] == "Bearer embedding-secret"
    assert "url" not in evidence["config"]
    assert "api_key" not in evidence["config"]


@pytest.mark.parametrize("inputs", [[], "bad", [""], [1]])
def test_live_embedding_batch_rejects_invalid_inputs(inputs):
    module = _module()
    with pytest.raises(ValueError, match="inputs"):
        module.request_live_embeddings(_live_env(module), inputs)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"data": []}, "count"),
        ({"data": ["bad"]}, "item"),
        (
            {"data": [{"index": 2, "embedding": [1.0] * 2560}]},
            "lineage",
        ),
        (
            {"data": [{"index": 0, "embedding": [1.0]}]},
            "dimension",
        ),
        (
            {"data": [{"index": 0, "embedding": [float("nan")] * 2560}]},
            "non-finite",
        ),
        (
            {"data": [{"index": 0, "embedding": [0.0] * 2560}]},
            "all zero",
        ),
    ],
)
def test_live_embedding_batch_rejects_invalid_responses(
    monkeypatch,
    payload,
    message,
):
    module = _module()
    monkeypatch.setattr(
        module,
        "execute_remote_embedding_request",
        lambda *_a, **_k: payload,
    )

    with pytest.raises(ValueError, match=message):
        module.request_live_embeddings(_live_env(module), ["query"])


def test_live_embedding_batch_rejects_duplicate_and_incomplete_lineage(monkeypatch):
    module = _module()
    vector = [1.0] + [0.0] * (module.VECTOR_DIMENSION - 1)
    monkeypatch.setattr(
        module,
        "execute_remote_embedding_request",
        lambda *_a, **_k: {
            "data": [
                {"index": 0, "embedding": vector},
                {"index": 0, "embedding": vector},
            ]
        },
    )
    with pytest.raises(ValueError, match="lineage"):
        module.request_live_embeddings(_live_env(module), ["query", "chunk"])


def test_success_failure_redaction_summary_and_main(monkeypatch, capsys):
    module = _module()
    database_url = (
        "postgresql://nex_cx_user:database-secret@localhost/nex_cx_test"
    )
    monkeypatch.setattr(module, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_a, **_k: database_url,
    )
    monkeypatch.setattr(
        module,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(applied=(), skipped=("existing",)),
    )
    execution = {
        "failed_checks": [],
        "check_count": 3,
        "provider": {"vector_dimension": 2560},
    }
    monkeypatch.setattr(module, "_execute_smoke", lambda *_a, **_k: execution)

    passing = module.run_cx_permission_hybrid_live_postgres_smoke(
        _live_env(module)
    )
    assert passing["status"] == "PASS"
    assert passing["remote_embedding_required"] is True
    assert passing["remote_reranker_required"] is True
    assert passing["migration"]["skipped"] == ["existing"]
    assert "checks=3/3" in module.summary_line(passing)

    monkeypatch.setattr(
        module,
        "_execute_smoke",
        lambda *_a, **_k: {"failed_checks": ["bm25"]},
    )
    failed = module.run_cx_permission_hybrid_live_postgres_smoke(
        _live_env(module)
    )
    assert failed["error"]["code"] == "permission_hybrid_live_smoke_failed"

    monkeypatch.setattr(
        module,
        "run_service_migrations",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    exception = module.run_cx_permission_hybrid_live_postgres_smoke(
        _live_env(module)
    )
    assert exception["error"] == {
        "code": "execution_failed",
        "detail": "RuntimeError",
    }

    assert module._target_url_allowed(database_url)
    assert not module._target_url_allowed(database_url.replace("test", "dev"))
    module.assert_evidence_redacted({"safe": True}, _live_env(module))
    with pytest.raises(ValueError, match="not redacted"):
        module.assert_evidence_redacted(
            {"leak": "embedding-secret"},
            _live_env(module),
        )
    assert "skipped" in module.summary_line({"status": "SKIPPED"})
    assert "error=boom" in module.summary_line(
        {"status": "FAIL", "error": {"code": "boom"}}
    )
    assert "error=unknown" in module.summary_line({})

    monkeypatch.setattr(
        module,
        "run_cx_permission_hybrid_live_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    assert module.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(
        module,
        "run_cx_permission_hybrid_live_postgres_smoke",
        lambda: {"status": "FAIL", "error": {"code": "boom"}},
    )
    assert module.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
