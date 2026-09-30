from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import nex_mo.remote_provider as remote_provider
from nex_mo.provider_telemetry_repository import (
    ProviderTelemetryRepositoryError,
    SqlAlchemyDurableProviderTelemetryRepository,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import issue_mock_service_token
from run_mo_provider_telemetry_restart_concurrency import _apply_sqlite_migration


def _auth_headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    return {"Authorization": f"Bearer {token.access_token}"}


def _app() -> FastAPI:
    app = FastAPI()
    register_mock_provider_routes(app)
    return app


@pytest.fixture(autouse=True)
def restore_store():
    prior = remote_provider.current_remote_provider_telemetry_store()
    yield
    remote_provider.configure_remote_provider_telemetry_store(prior)


def test_authenticated_api_recovers_durable_snapshot_after_store_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    _apply_sqlite_migration(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    env = {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://private-provider/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-api-key",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "EmbeddingRuntime",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "embedding-revision-a",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "embedding-deployment-a",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config = remote_provider.build_remote_embedding_execution_config(env)
    first = DurableProviderTelemetryStore(
        SqlAlchemyDurableProviderTelemetryRepository(factory)
    )
    first.record_success(
        config,
        latency_ms=17,
        observed_at="2026-09-30T01:00:00Z",
    )
    restarted = DurableProviderTelemetryStore(
        SqlAlchemyDurableProviderTelemetryRepository(factory)
    )
    remote_provider.configure_remote_provider_telemetry_store(restarted)

    unauthorized = TestClient(_app()).get("/api/v1/provider-telemetry")
    response = TestClient(_app()).get(
        "/api/v1/provider-telemetry",
        params={"capability": "embedding"},
        headers=_auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == {
        "count": 1,
        "provider_mode": "live",
        "schema_version": "mo_provider_telemetry_snapshot.v1",
    }
    assert payload["data"][0]["request_count"] == 1
    assert payload["data"][0]["success_count"] == 1
    assert payload["data"][0]["last_latency_ms"] == 17
    assert "private-provider" not in str(payload)
    assert "private-api-key" not in str(payload)
    assert restarted._repository.clear() == 1


def test_authenticated_api_returns_safe_503_when_repository_is_unavailable() -> None:
    class FailingStore:
        def snapshot(self, *_args: object, **_kwargs: object):
            raise ProviderTelemetryRepositoryError("private database detail")

        def reset(self) -> None:  # pragma: no cover - API read only
            return None

        def record_success(self, *_args: object, **_kwargs: object) -> None:
            return None

        def record_failure(self, *_args: object, **_kwargs: object) -> None:
            return None

        def record_retry(self, *_args: object, **_kwargs: object) -> None:
            return None

    remote_provider.configure_remote_provider_telemetry_store(FailingStore())

    response = TestClient(_app()).get(
        "/api/v1/provider-telemetry",
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "MO_PROVIDER_TELEMETRY_UNAVAILABLE"
    assert "private database detail" not in str(response.json())
