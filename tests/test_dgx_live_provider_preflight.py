from __future__ import annotations

import json
from urllib.error import URLError

import pytest

import run_dgx_live_provider_preflight as dgx_preflight


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload.encode("utf-8")


def live_env() -> dict[str, str]:
    return {
        "NEX_MO_LIVE_PREFLIGHT": "1",
        "NEX_MO_LIVE_EMBEDDING_HEALTH_URL": "http://dgx.local/embed/health",
        "NEX_MO_LIVE_RERANKER_HEALTH_URL": "http://dgx.local/rerank/health",
        "NEX_MO_LIVE_VLLM_MODELS_URL": "http://dgx.local/v1/models",
    }


def test_dgx_preflight_skips_when_not_enabled() -> None:
    evidence = dgx_preflight.run_dgx_live_provider_preflight({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["checks"] == []
    assert "qwen3_5_122b_a10b_nvfp4" in {
        profile["profile_name"] for profile in evidence["model_profiles"]
    }


def test_dgx_preflight_passes_when_expected_models_are_observed() -> None:
    calls: list[tuple[str, int]] = []

    def opener(url: str, *, timeout: int) -> FakeResponse:
        calls.append((url, timeout))
        return FakeResponse(
            json.dumps(
                {
                    "models": [
                        "Qwen3-embedding-4B",
                        "Qwen3-reranker-4B",
                        "Qwen3.5-122B-A10B-NVFP4",
                        "Qwen3.6-27B-NVFP4",
                    ]
                }
            )
        )

    evidence = dgx_preflight.run_dgx_live_provider_preflight(
        {**live_env(), "NEX_MO_LIVE_TIMEOUT_SECONDS": "7"},
        opener=opener,
    )

    assert evidence["status"] == "PASS"
    assert [check["status"] for check in evidence["checks"]] == ["PASS", "PASS", "PASS"]
    assert calls == [
        ("http://dgx.local/embed/health", 7),
        ("http://dgx.local/rerank/health", 7),
        ("http://dgx.local/v1/models", 7),
    ]
    assert "dgx.local" not in json.dumps(evidence)


def test_dgx_preflight_reports_missing_endpoint_and_model() -> None:
    def opener(url: str, *, timeout: int) -> FakeResponse:
        return FakeResponse("Qwen3-embedding-4B Qwen3-reranker-4B")

    evidence = dgx_preflight.run_dgx_live_provider_preflight(
        {
            "NEX_MO_LIVE_PREFLIGHT": "1",
            "NEX_MO_LIVE_EMBEDDING_HEALTH_URL": "http://dgx.local/embed/health",
            "NEX_MO_LIVE_RERANKER_HEALTH_URL": "http://dgx.local/rerank/health",
            "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": "CustomGeneration",
        },
        opener=opener,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][2]["failure_code"] == "endpoint_not_configured"

    missing_model = dgx_preflight.run_dgx_live_provider_preflight(
        live_env(),
        opener=opener,
    )
    assert missing_model["status"] == "FAIL"
    assert missing_model["checks"][2]["failure_code"] == "expected_model_missing"
    assert missing_model["checks"][2]["missing_expected_models"] == [
        "Qwen3.5-122B-A10B-NVFP4",
        "Qwen3.6-27B-NVFP4",
    ]


def test_dgx_preflight_reports_fetch_errors_and_env_model_overrides() -> None:
    def opener(url: str, *, timeout: int) -> FakeResponse:
        raise URLError("down")

    evidence = dgx_preflight.run_dgx_live_provider_preflight(
        {
            **live_env(),
            "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "EmbedA, EmbedB",
        },
        opener=opener,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][0]["expected_models"] == ["EmbedA", "EmbedB"]
    assert evidence["checks"][0]["failure_code"] == "URLError"


def test_dgx_preflight_main_summary_and_output(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.delenv("NEX_MO_LIVE_PREFLIGHT", raising=False)

    assert dgx_preflight.main(["--summary"]) == 0
    assert "dgx_live_provider_preflight=skipped" in capsys.readouterr().out

    output = tmp_path / "dgx-preflight.json"
    assert dgx_preflight.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "SKIPPED"


def test_dgx_preflight_main_returns_failure_when_enabled_without_urls(monkeypatch) -> None:
    monkeypatch.setenv("NEX_MO_LIVE_PREFLIGHT", "1")
    for check in dgx_preflight.LIVE_PROVIDER_CHECKS:
        monkeypatch.delenv(check.endpoint_env, raising=False)

    assert dgx_preflight.main(["--summary"]) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ("Default",)),
        ("", ("Default",)),
        ("A, B,,", ("A", "B")),
    ],
)
def test_expected_models_from_env(value: str | None, expected: tuple[str, ...]) -> None:
    assert dgx_preflight.expected_models_from_env(value, ("Default",)) == expected
