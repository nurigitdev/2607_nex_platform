from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime import DEFAULT_SERVICE_SCOPE, resolve_service_endpoint

from .agent_result_source import (
    EOS_PROJECT_VERIFY_SCOPE,
    WORK_SOURCE_READ_SCOPE,
    AeAgentResultSourceAdapter,
    HttpAeAgentResultProjectionClient,
    HttpEosProjectVerificationClient,
    HttpWcWorkResultProjectionClient,
)
from .artifact_source import (
    AeArtifactSourceAdapter,
    HttpAeArtifactProjectionClient,
    HttpEosHistoricalMembershipVerificationClient,
    HttpOaHumanSubjectVerificationClient,
)
from .config import WaSettings, load_wa_settings
from .consumer import (
    DEFAULT_WORKER_ID,
    WaEvidenceConsumerRuntime,
    build_wa_evidence_consumer_runtime,
)
from .persistence import WaPersistenceRuntime, build_wa_persistence_runtime
from .service_auth import resolve_wa_outbound_service_token
from .source_adapters import WaEvidenceSourceAdapterRegistry

OA_SUBJECT_VERIFY_SCOPE = "identity:subject:verify"


@dataclass(frozen=True)
class WaInstalledConsumerProcess:
    settings: WaSettings
    persistence: WaPersistenceRuntime
    runtime: WaEvidenceConsumerRuntime

    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "wa_installed_consumer_process.v1",
            "service_id": "nex-wa",
            "process_id": "nex-wa-evidence-consumer",
            "worker_id": self.runtime.config.worker_id,
            "worker_type": self.runtime.config.worker_type,
            "profile": self.settings.profile,
            "database_env": self.settings.database_env,
            "work_claiming_enabled": True,
        }

    def startup(self) -> dict[str, Any]:
        self.runtime.require_ready()
        recovered = self.runtime.recover_stale(
            observed_at=_wire_now(),
            stale_after_seconds=self.settings.stale_job_seconds,
        )
        return {
            "readiness_status": "READY",
            "recovered_job_count": len(recovered),
        }

    def run_once(self) -> dict[str, Any]:
        execution = self.runtime.run_once()
        return execution.to_summary()

    def close(self) -> None:
        try:
            self.runtime.stop(observed_at=_wire_now())
        finally:
            self.persistence.dispose()


def build_installed_source_registry(
    *,
    environ: Mapping[str, str],
    persistence: WaPersistenceRuntime,
    endpoint_resolver=resolve_service_endpoint,
    token_resolver=resolve_wa_outbound_service_token,
) -> WaEvidenceSourceAdapterRegistry:
    endpoints = {
        service_id: endpoint_resolver(service_id, environ=environ).base_url
        for service_id in ("nex-ae-api", "nex-wc", "nex-oa", "nex-eos")
    }
    tokens = {
        "nex-ae-api": token_resolver(
            None,
            audience="nex-ae-api",
            scopes=(DEFAULT_SERVICE_SCOPE, WORK_SOURCE_READ_SCOPE),
            environ=environ,
        ),
        "nex-wc": token_resolver(
            None,
            audience="nex-wc",
            scopes=(DEFAULT_SERVICE_SCOPE, WORK_SOURCE_READ_SCOPE),
            environ=environ,
        ),
        "nex-oa": token_resolver(
            None,
            audience="nex-oa",
            scopes=(DEFAULT_SERVICE_SCOPE, OA_SUBJECT_VERIFY_SCOPE),
            environ=environ,
        ),
        "nex-eos": token_resolver(
            None,
            audience="nex-eos",
            scopes=(DEFAULT_SERVICE_SCOPE, EOS_PROJECT_VERIFY_SCOPE),
            environ=environ,
        ),
    }
    admission = persistence.evidence_admission_service
    return WaEvidenceSourceAdapterRegistry(
        {
            "AE_AGENT_RESULT": AeAgentResultSourceAdapter(
                source=HttpAeAgentResultProjectionClient(
                    base_url=endpoints["nex-ae-api"],
                    service_token=tokens["nex-ae-api"],
                ),
                admission=admission,
                projects=HttpEosProjectVerificationClient(
                    base_url=endpoints["nex-eos"],
                    service_token=tokens["nex-eos"],
                ),
                work_results=HttpWcWorkResultProjectionClient(
                    base_url=endpoints["nex-wc"],
                    service_token=tokens["nex-wc"],
                ),
            ),
            "AE_ARTIFACT": AeArtifactSourceAdapter(
                source=HttpAeArtifactProjectionClient(
                    base_url=endpoints["nex-ae-api"],
                    service_token=tokens["nex-ae-api"],
                ),
                subjects=HttpOaHumanSubjectVerificationClient(
                    base_url=endpoints["nex-oa"],
                    service_token=tokens["nex-oa"],
                ),
                admission=admission,
                memberships=HttpEosHistoricalMembershipVerificationClient(
                    base_url=endpoints["nex-eos"],
                    service_token=tokens["nex-eos"],
                ),
            ),
        }
    )


def build_installed_consumer_process(
    *,
    environ: Mapping[str, str],
    persistence_builder=build_wa_persistence_runtime,
    registry_builder=build_installed_source_registry,
    runtime_builder=build_wa_evidence_consumer_runtime,
) -> WaInstalledConsumerProcess:
    persistence: WaPersistenceRuntime | None = None
    try:
        settings = load_wa_settings(environ)
        persistence = persistence_builder(environ=environ)
        registry = registry_builder(environ=environ, persistence=persistence)
        worker_id = _worker_id(environ.get("NEX_WA_WORKER_ID", DEFAULT_WORKER_ID))
        runtime = runtime_builder(
            persistence=persistence,
            registry=registry,
            worker_id=worker_id,
        )
        return WaInstalledConsumerProcess(settings, persistence, runtime)
    except Exception:
        if persistence is not None:
            persistence.dispose()
        raise


def _worker_id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("NEX_WA_WORKER_ID must be a non-empty trimmed string")
    if len(value) > 128:
        raise ValueError("NEX_WA_WORKER_ID exceeds 128 characters")
    return value


def _wire_now(clock: Callable[[], datetime] | None = None) -> str:
    value = (clock or (lambda: datetime.now(UTC)))()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("WA installed consumer clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
