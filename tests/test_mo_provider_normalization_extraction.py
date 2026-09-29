from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nex_mo import provider_normalization, remote_provider
from nex_mo.providers import ProviderRouteError
import run_mo_provider_normalization_extraction as runner


CONFIG = SimpleNamespace(model_revision="revision", deployment_id="deployment")


def test_remote_provider_preserves_normalizer_exports() -> None:
    assert remote_provider.normalize_remote_embedding_response is (
        provider_normalization.normalize_remote_embedding_response
    )
    assert remote_provider.normalize_remote_rerank_response is (
        provider_normalization.normalize_remote_rerank_response
    )
    assert remote_provider.normalize_remote_generation_response is (
        provider_normalization.normalize_remote_generation_response
    )


def test_embedding_normalization_covers_legacy_and_invalid_items() -> None:
    result = provider_normalization.normalize_remote_embedding_response(
        provider_payload={"embeddings": [[1, 2]]},
        alias="alias",
        config=CONFIG,
        input_count=1,
        input_texts=["two tokens"],
    )

    assert result["data"] == [{"object": "embedding", "index": 0, "embedding": [1.0, 2.0]}]
    assert result["usage"]["input_tokens"] == 2
    with pytest.raises(ProviderRouteError) as exc_info:
        provider_normalization.normalize_remote_embedding_response(
            provider_payload={"data": "invalid"},
            alias="alias",
            config=CONFIG,
            input_count=1,
            input_texts=["text"],
        )
    assert "count did not match" in exc_info.value.detail


def test_generation_and_rerank_normalization_preserve_edge_contracts() -> None:
    generation = provider_normalization.normalize_remote_generation_response(
        provider_payload={
            "choices": [{"text": "answer", "finish_reason": "custom"}],
            "usage": {"prompt_tokens": -1, "completion_tokens": 2},
        },
        alias="alias",
        route_id="route",
        config=CONFIG,
        request_id="request",
        trace_id="trace",
        input_texts=["prompt"],
    )
    rerank = provider_normalization.normalize_remote_rerank_response(
        provider_payload={
            "data": [
                {"index": 1, "score": 0.1, "document": {"text": "second"}},
                {"index": 0, "score": 0.9},
            ]
        },
        alias="alias",
        config=CONFIG,
        documents=["first", "second"],
        query="query",
    )

    assert generation["finish_reason"] == "CUSTOM"
    assert generation["usage"] == {"input_tokens": 0, "output_tokens": 2, "total_tokens": 2}
    assert rerank["results"][0]["document"] == "first"


def test_normalization_extraction_evidence_and_runner(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    missing = runner.run_mo_provider_normalization_extraction(tmp_path)
    assert missing["status"] == "FAIL"
    assert missing["summary"]["failed_check_count"] == 2

    passing = runner.run_mo_provider_normalization_extraction()
    assert passing["status"] == "PASS"
    monkeypatch.setattr(runner, "run_mo_provider_normalization_extraction", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "normalizers=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_provider_normalization_extraction", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "normalization_extraction=fail" in capsys.readouterr().out
