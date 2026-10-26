from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import quote

from .demo_domain_activation import DEMO_DOMAIN_PROCESSES
from .demo_trust import DEMO_OWNERS
from .semantic_hashes import semantic_sha256_hash_ref

DEMO_DOMAIN_INSTALLATION_SCHEMA_VERSION = "p8_demo_domain_installation.v1"
DEMO_RUNTIME_APPROLE_SECRET_ID_TTL = "24h"
DEMO_RUNTIME_APPROLE_SECRET_ID_TTL_SECONDS = 86_400
DEMO_RUNTIME_APPROLE_SECRET_ID_NUM_USES = 0
DEMO_DOMAIN_WORKERS = {
    "nex-ae-agent-runtime-worker": (
        "nex-ae-api",
        "ae-demo-agent-runtime-1",
        "ae.agent_runtime.worker",
    ),
    "nex-wc-event-delivery-worker": (
        "nex-wc",
        "wc-demo-event-delivery-1",
        "wc.event_delivery.worker",
    ),
    "nex-eos-outbox-publisher": (
        "nex-eos",
        "eos-demo-outbox-publisher-1",
        "eos.outbox.publisher",
    ),
}


class DemoDomainInstallationError(ValueError):
    pass


class OpenBaoDemoAdminClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


def configure_demo_runtime_approles(
    client: OpenBaoDemoAdminClient,
    *,
    root_token: str,
    owners: Sequence[str] = DEMO_OWNERS,
) -> dict[str, Any]:
    """Make owner credentials reusable across API/worker startup and restart."""

    admitted = _owners(owners)
    if not isinstance(root_token, str) or not root_token.strip():
        raise DemoDomainInstallationError("Demo OpenBao root token is invalid")
    for owner in admitted:
        role_name = f"{owner}-staging"
        client.request(
            "POST",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}",
            token=root_token,
            payload={
                "token_policies": [f"{owner}-staging"],
                "token_ttl": "5m",
                "token_max_ttl": "10m",
                "secret_id_ttl": DEMO_RUNTIME_APPROLE_SECRET_ID_TTL,
                "secret_id_num_uses": DEMO_RUNTIME_APPROLE_SECRET_ID_NUM_USES,
            },
        )
        response = client.request(
            "GET",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}",
            token=root_token,
        )
        data = response.get("data")
        if not isinstance(data, Mapping) or (
            _integer(data.get("secret_id_ttl"), default=0)
            != DEMO_RUNTIME_APPROLE_SECRET_ID_TTL_SECONDS
            or _integer(data.get("secret_id_num_uses"), default=-1)
            != DEMO_RUNTIME_APPROLE_SECRET_ID_NUM_USES
        ):
            raise DemoDomainInstallationError(
                f"Demo runtime AppRole policy drift: {owner}"
            )
    payload = {
        "schema_version": DEMO_DOMAIN_INSTALLATION_SCHEMA_VERSION,
        "status": "CONFIGURED",
        "deployment_boundary": "P8_DEMO",
        "owner_count": len(admitted),
        "secret_id_ttl_seconds": DEMO_RUNTIME_APPROLE_SECRET_ID_TTL_SECONDS,
        "secret_id_num_uses": DEMO_RUNTIME_APPROLE_SECRET_ID_NUM_USES,
        "shared_api_worker_credential": True,
        "restart_reauthentication_supported": True,
        "credential_values_included": False,
    }
    return {**payload, "policy_hash": semantic_sha256_hash_ref(payload)}


def admit_demo_domain_runtime_evidence(
    *,
    initial_heartbeats: Mapping[str, Mapping[str, Any]],
    restarted_heartbeats: Mapping[str, Mapping[str, Any]],
    token_runtimes: Mapping[str, Mapping[str, Any]],
    bootstrap_log_counts: Mapping[str, int],
) -> dict[str, Any]:
    expected_processes = set(DEMO_DOMAIN_PROCESSES)
    if set(initial_heartbeats) != expected_processes or set(
        restarted_heartbeats
    ) != expected_processes:
        raise DemoDomainInstallationError(
            "Demo domain heartbeat process coverage is incomplete"
        )
    for process_id, expected in DEMO_DOMAIN_WORKERS.items():
        initial = initial_heartbeats[process_id]
        restarted = restarted_heartbeats[process_id]
        identity = tuple(
            initial.get(name) for name in ("service_id", "worker_id", "worker_type")
        )
        if identity != expected or tuple(
            restarted.get(name) for name in ("service_id", "worker_id", "worker_type")
        ) != expected:
            raise DemoDomainInstallationError(
                f"Demo domain heartbeat identity drift: {process_id}"
            )
        if (
            initial.get("status") != "IDLE"
            or restarted.get("status") != "IDLE"
            or initial.get("observed_at") == restarted.get("observed_at")
        ):
            raise DemoDomainInstallationError(
                f"Demo domain restart heartbeat was not renewed: {process_id}"
            )
    expected_services = {"nex-oa", "nex-ae-api", "nex-wc", "nex-eos"}
    if set(token_runtimes) != expected_services:
        raise DemoDomainInstallationError(
            "Demo signed-token runtime coverage is incomplete"
        )
    for service_id, runtime in token_runtimes.items():
        counts = runtime.get("admission_counts")
        if (
            runtime.get("rollout_profile") != "SIGNED_ONLY"
            or not isinstance(counts, Mapping)
            or int(counts.get("accepted_signed") or 0) < 1
            or int(counts.get("accepted_mock") or 0) != 0
        ):
            raise DemoDomainInstallationError(
                f"Demo signed-token admission drift: {service_id}"
            )
    if set(bootstrap_log_counts) != expected_processes or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 2
        for value in bootstrap_log_counts.values()
    ):
        raise DemoDomainInstallationError(
            "Demo domain startup token bootstrap was not repeated after restart"
        )
    payload = {
        "schema_version": DEMO_DOMAIN_INSTALLATION_SCHEMA_VERSION,
        "status": "PASS",
        "process_count": len(expected_processes),
        "signed_service_count": len(expected_services),
        "domain_claiming_enabled": True,
        "signed_only": True,
        "accepted_mock_token_count": 0,
        "startup_token_bootstrap_repeated": True,
        "restart_heartbeat_renewed": True,
        "new_business_behavior_added": False,
        "secret_included": False,
        "token_value_included": False,
    }
    return {**payload, "evidence_hash": semantic_sha256_hash_ref(payload)}


def _owners(values: Sequence[str]) -> tuple[str, ...]:
    owners = tuple(values)
    if (
        not owners
        or len(owners) != len(set(owners))
        or any(owner not in DEMO_OWNERS for owner in owners)
    ):
        raise DemoDomainInstallationError("Demo runtime AppRole owner set is invalid")
    return owners


def _integer(value: object, *, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
