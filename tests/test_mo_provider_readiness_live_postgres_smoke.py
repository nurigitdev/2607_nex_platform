from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_mo_provider_readiness_live_postgres_smoke as smoke


ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_MO_TEST_DATABASE_URL": (
            "postgresql://nex_mo_user:private-db-secret@localhost/nex_mo_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://private.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://private.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_VLLM_BASE_URL": "http://private.local:9111",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
    }


def _provider_payload() -> dict[str, object]:
    payload = json.loads(
        (
            ROOT
            / "contracts/examples/provider/mo_provider_readiness.mock_ready.json"
        ).read_text(encoding="utf-8")
    )
    payload["provider_mode"] = "live"
    payload["checked_at"] = "2026-09-30T01:00:00Z"
    payload["expires_at"] = "2026-09-30T01:01:00Z"
    for route, capability, model in zip(
        payload["routes"],
        ("embedding", "reranking", "generation"),
        ("Qwen3-Embedding-4B", "Qwen3-Reranker-4B", "Qwen3.5-4B"),
        strict=True,
    ):
        route["provider_capability"] = capability
        route["source"] = "active_preflight"
        route["model_revision"] = model
        route["checked_at"] = payload["checked_at"]
        route["latency_ms"] = 7
    return payload


class StubClient:
    def __init__(
        self,
        *,
        ready_status: int = 200,
        provider_payload: dict[str, object] | None = None,
    ) -> None:
        provider = provider_payload or _provider_payload()
        self._ready_status = ready_status
        self._provider = provider

    def get(self, url: str, *, headers=None):
        if url == "/ready":
            return SimpleNamespace(
                status_code=self._ready_status,
                json=lambda: {
                    "service_id": "nex-mo",
                    "readiness_status": "READY",
                    "checks": [
                        {
                            "name": "database",
                            "ok": True,
                            "database_name": "nex_mo_test",
                            "database_user": "nex_mo_user",
                            "latency_ms": 2,
                        },
                        deepcopy(self._provider),
                    ],
                },
            )
        if headers is None:
            return SimpleNamespace(status_code=401, json=lambda: {"status": 401})
        return SimpleNamespace(
            status_code=200,
            json=lambda: deepcopy(self._provider),
        )


def test_smoke_is_explicitly_protected() -> None:
    evidence = smoke.run_mo_provider_readiness_live_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in evidence["skip_reason"]
    assert smoke.main(["--summary"]) == 0


def test_smoke_rejects_non_test_profile_and_missing_configuration() -> None:
    invalid_profile = smoke.run_mo_provider_readiness_live_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    missing = smoke.run_mo_provider_readiness_live_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )

    assert invalid_profile["failure_code"] == "profile_not_allowed"
    assert missing["failure_code"] == "configuration_invalid"
    assert missing["diagnostics"]["missing_env"] == [
        "NEX_MO_TEST_DATABASE_URL",
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_RERANKER_URL",
        "NEX_MO_VLLM_MODELS_URL|NEX_MO_VLLM_BASE_URL",
    ]


def test_smoke_proves_database_provider_cache_auth_and_redaction() -> None:
    evidence = smoke.run_mo_provider_readiness_live_postgres_smoke(
        _env(),
        client_factory=StubClient,
    )
    serialized = json.dumps(evidence)

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["database_identity"] == {
        "database_name": "nex_mo_test",
        "database_user": "nex_mo_user",
        "latency_ms": 2,
    }
    assert evidence["provider_models"] == {
        "embedding": "Qwen3-Embedding-4B",
        "reranking": "Qwen3-Reranker-4B",
        "generation": "Qwen3.5-4B",
    }
    assert evidence["summary"]["passed_check_count"] == 8
    assert "private-db-secret" not in serialized
    assert "private.local" not in serialized
    assert "generation-secret" not in serialized
    assert smoke.summary_line(evidence).endswith("providers=3/3 next=1131")


def test_smoke_fails_closed_for_http_or_payload_drift() -> None:
    http_failure = smoke.run_mo_provider_readiness_live_postgres_smoke(
        _env(),
        client_factory=lambda: StubClient(ready_status=503),
    )
    invalid_payload = _provider_payload()
    invalid_payload["private_endpoint"] = "http://private.local:9112"
    contract_failure = smoke.run_mo_provider_readiness_live_postgres_smoke(
        _env(),
        client_factory=lambda: StubClient(provider_payload=invalid_payload),
    )

    assert http_failure["status"] == "FAIL"
    assert http_failure["checks"]["ready_route_succeeded"] is False
    assert contract_failure["failure_code"] == "live_execution_failed"
    assert contract_failure["diagnostics"]["exception_type"] == "ValidationError"
    assert "private.local" not in json.dumps(contract_failure)


def test_smoke_helpers_and_redaction_fail_closed() -> None:
    assert smoke._json_object(SimpleNamespace(json=lambda: {"ok": True})) == {
        "ok": True
    }
    with pytest.raises(ValueError, match="response_not_json_object"):
        smoke._json_object(SimpleNamespace(json=lambda: []))
    with pytest.raises(ValueError, match="database_readiness_check_missing"):
        smoke._database_check({"checks": []})
    with pytest.raises(ValueError, match="provider_readiness_check_missing"):
        smoke._provider_check({"checks": [{"name": "database"}]})

    assert smoke._failure("safe_failure") == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "slice": "1130",
        "requirement": "S113",
        "status": "FAIL",
        "failure_code": "safe_failure",
        "issues": ["safe_failure"],
        "next_slice": None,
    }
    smoke.assert_evidence_redacted({"safe": True}, {})
    smoke.assert_evidence_redacted({"safe": True}, _env())
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted(
            {"leak": "generation-secret"},
            _env(),
        )
    malformed = _env()
    malformed["NEX_MO_TEST_DATABASE_URL"] = "not-a-database-url"
    smoke.assert_evidence_redacted({"safe": True}, malformed)


def test_redaction_tolerates_unparseable_database_url(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "make_url",
        lambda _value: (_ for _ in ()).throw(ValueError("private detail")),
    )

    smoke.assert_evidence_redacted({"safe": True}, _env())


def test_smoke_main_success_and_failure_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_provider_readiness_live_postgres_smoke(
        _env(), client_factory=StubClient
    )
    monkeypatch.setattr(
        smoke,
        "run_mo_provider_readiness_live_postgres_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=8/8" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_mo_provider_readiness_live_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
