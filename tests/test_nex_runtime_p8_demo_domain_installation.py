from __future__ import annotations

from typing import Any

import pytest
from nex_runtime.demo_domain_installation import (
    DEMO_DOMAIN_WORKERS,
    DemoDomainInstallationError,
    admit_demo_domain_runtime_evidence,
    configure_demo_runtime_approles,
)


class _OpenBaoAdmin:
    def __init__(self, *, drift: bool = False, malformed: bool = False) -> None:
        self.drift = drift
        self.malformed = malformed
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append((method, path, dict(payload or {})))
        if method == "GET":
            return {
                "data": {
                    "secret_id_ttl": "invalid" if self.malformed else 86_400,
                    "secret_id_num_uses": 1 if self.drift else 0,
                }
            }
        return {}


def _heartbeats(observed_at: str) -> dict[str, dict[str, Any]]:
    return {
        process_id: {
            "service_id": identity[0],
            "worker_id": identity[1],
            "worker_type": identity[2],
            "status": "IDLE",
            "observed_at": observed_at,
        }
        for process_id, identity in DEMO_DOMAIN_WORKERS.items()
    }


def _token_runtimes() -> dict[str, dict[str, Any]]:
    return {
        service_id: {
            "rollout_profile": "SIGNED_ONLY",
            "admission_counts": {
                "accepted_signed": 1,
                "accepted_mock": 0,
                "rejected": 0,
            },
        }
        for service_id in ("nex-oa", "nex-ae-api", "nex-wc", "nex-eos")
    }


def test_demo_runtime_approles_are_restartable_but_still_owner_scoped() -> None:
    admin = _OpenBaoAdmin()

    result = configure_demo_runtime_approles(
        admin,
        root_token="root-token-private",
        owners=("nex-ae-api", "nex-wc", "nex-eos"),
    )

    writes = [request for request in admin.requests if request[0] == "POST"]
    assert result["status"] == "CONFIGURED"
    assert result["secret_id_ttl_seconds"] == 86_400
    assert result["secret_id_num_uses"] == 0
    assert result["credential_values_included"] is False
    assert len(writes) == 3
    assert writes[0][2] == {
        "token_policies": ["nex-ae-api-staging"],
        "token_ttl": "5m",
        "token_max_ttl": "10m",
        "secret_id_ttl": "24h",
        "secret_id_num_uses": 0,
    }


def test_demo_runtime_approle_policy_fails_closed_on_drift_and_bad_owner() -> None:
    with pytest.raises(DemoDomainInstallationError, match="policy drift"):
        configure_demo_runtime_approles(
            _OpenBaoAdmin(drift=True),
            root_token="root-token-private",
            owners=("nex-ae-api",),
        )
    with pytest.raises(DemoDomainInstallationError, match="owner set"):
        configure_demo_runtime_approles(
            _OpenBaoAdmin(),
            root_token="root-token-private",
            owners=("unknown",),
        )
    with pytest.raises(DemoDomainInstallationError, match="owner set"):
        configure_demo_runtime_approles(
            _OpenBaoAdmin(),
            root_token="root-token-private",
            owners=("nex-ae-api", "nex-ae-api"),
        )
    with pytest.raises(DemoDomainInstallationError, match="policy drift"):
        configure_demo_runtime_approles(
            _OpenBaoAdmin(malformed=True),
            root_token="root-token-private",
            owners=("nex-ae-api",),
        )
    with pytest.raises(DemoDomainInstallationError, match="root token"):
        configure_demo_runtime_approles(_OpenBaoAdmin(), root_token="")


def test_domain_runtime_evidence_requires_signed_restart_observations() -> None:
    result = admit_demo_domain_runtime_evidence(
        initial_heartbeats=_heartbeats("2026-10-26T01:00:00Z"),
        restarted_heartbeats=_heartbeats("2026-10-26T01:01:00Z"),
        token_runtimes=_token_runtimes(),
        bootstrap_log_counts={process_id: 2 for process_id in DEMO_DOMAIN_WORKERS},
    )

    assert result["status"] == "PASS"
    assert result["process_count"] == 3
    assert result["signed_service_count"] == 4
    assert result["accepted_mock_token_count"] == 0
    assert result["new_business_behavior_added"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing_heartbeat", "coverage"),
        ("stale_restart", "not renewed"),
        ("mock_token", "admission drift"),
        ("missing_token_runtime", "runtime coverage"),
        ("identity_drift", "identity drift"),
        ("single_bootstrap", "not repeated"),
    ),
)
def test_domain_runtime_evidence_rejects_incomplete_acceptance(
    mutation: str, message: str
) -> None:
    initial = _heartbeats("2026-10-26T01:00:00Z")
    restarted = _heartbeats("2026-10-26T01:01:00Z")
    runtimes = _token_runtimes()
    logs = {process_id: 2 for process_id in DEMO_DOMAIN_WORKERS}
    if mutation == "missing_heartbeat":
        initial.pop("nex-eos-outbox-publisher")
    elif mutation == "stale_restart":
        restarted = _heartbeats("2026-10-26T01:00:00Z")
    elif mutation == "mock_token":
        runtimes["nex-wc"]["admission_counts"]["accepted_mock"] = 1
    elif mutation == "missing_token_runtime":
        runtimes.pop("nex-eos")
    elif mutation == "identity_drift":
        restarted["nex-wc-event-delivery-worker"]["worker_id"] = "wrong"
    else:
        logs["nex-wc-event-delivery-worker"] = 1

    with pytest.raises(DemoDomainInstallationError, match=message):
        admit_demo_domain_runtime_evidence(
            initial_heartbeats=initial,
            restarted_heartbeats=restarted,
            token_runtimes=runtimes,
            bootstrap_log_counts=logs,
        )
