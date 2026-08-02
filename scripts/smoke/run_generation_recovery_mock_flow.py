from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ag",
    "services/nex-ae-api",
    "services/nex-cx",
):
    sys.path.insert(0, str(ROOT_DIR / service_path))

from nex_ae_api.recovery_requests import (
    GenerationRecoveryRequestStore,
    register_generation_recovery_request_routes,
)
from nex_ag.generation_audit import register_generation_audit_routes
from nex_cx.generation import (
    GenerationExecutionStore,
    GenerationFacadeError,
    register_generation_routes,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
RECOVERY_SMOKE_PROMPT = "Trigger a retryable provider timeout for recovery smoke."


@dataclass
class TimeoutMoGenerationClient:
    last_payload: dict[str, Any] | None = None

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.last_payload = payload
        raise GenerationFacadeError(
            status_code=504,
            error_code="mo.provider_timeout",
            detail="Provider timed out.",
            retryable=True,
        )


@dataclass
class TestClientCxRecoverySourceClient:
    client: TestClient

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            f"/api/v1/generations/{cx_generation_id}",
            headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
        )
        response.raise_for_status()
        return response.json()


@dataclass
class TestClientGenerationAuditSourceClient:
    cx_client: TestClient
    ae_client: TestClient

    def get_cx_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.cx_client.get(
            f"/api/v1/generations/{cx_generation_id}",
            headers=service_headers("nex-ag", "nex-cx", trace_id, request_id),
        )
        response.raise_for_status()
        return response.json()

    def get_cx_generation_events(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.cx_client.get(
            f"/api/v1/generations/{cx_generation_id}/events",
            headers=service_headers("nex-ag", "nex-cx", trace_id, request_id),
        )
        response.raise_for_status()
        return response.json()

    def get_ae_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.ae_client.get(
            f"/api/v1/artifact-handoffs/{artifact_handoff_id}",
            headers=service_headers("nex-ag", "nex-ae-api", trace_id, request_id),
        )
        response.raise_for_status()
        return response.json()

    def get_ae_recovery_request(
        self,
        recovery_request_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.ae_client.get(
            f"/api/v1/recovery/generation-requests/{recovery_request_id}",
            headers=service_headers("nex-ag", "nex-ae-api", trace_id, request_id),
        )
        response.raise_for_status()
        return response.json()


def run_generation_recovery_mock_flow(trace_id: str = TRACE_ID) -> dict[str, Any]:
    request_id = REQUEST_ID

    mo_client = TimeoutMoGenerationClient()
    cx_store = GenerationExecutionStore()
    cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(cx_app, store=cx_store, mo_client=mo_client)
    cx_test_client = TestClient(cx_app)

    failed = cx_test_client.post(
        "/api/v1/generations",
        json={
            "trace_id": trace_id,
            "prompt": RECOVERY_SMOKE_PROMPT,
            "alias": "general-llm-default",
        },
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    if failed.status_code != 504:
        raise AssertionError(f"expected retryable CX failure, got {failed.status_code}")
    if mo_client.last_payload is None:
        raise AssertionError("MO timeout client did not receive a generation payload")
    cx_generation_id = mo_client.last_payload["cx_generation_id"]

    cx_record = cx_store.get(cx_generation_id)
    if cx_record is None:
        raise AssertionError("CX failed generation record was not stored")
    cx_events = cx_test_client.get(
        f"/api/v1/generations/{cx_generation_id}/events",
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    cx_events.raise_for_status()

    ae_store = GenerationRecoveryRequestStore()
    ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_generation_recovery_request_routes(
        ae_app,
        store=ae_store,
        cx_client=TestClientCxRecoverySourceClient(cx_test_client),
    )
    ae_test_client = TestClient(ae_app)
    recovery_response = ae_test_client.post(
        "/api/v1/recovery/generation-requests",
        json={
            "trace_id": trace_id,
            "cx_generation_id": cx_generation_id,
            "requested_action": "retry",
            "interaction_id": "ae-recovery-smoke-interaction",
            "chat_document_id": "ae-recovery-smoke-chat",
        },
        headers=service_headers("nex-oa", "nex-ae-api", trace_id, request_id),
    )
    recovery_response.raise_for_status()
    recovery_request = recovery_response.json()

    ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_generation_audit_routes(
        ag_app,
        source_client=TestClientGenerationAuditSourceClient(
            cx_client=cx_test_client,
            ae_client=ae_test_client,
        ),
    )
    ag_response = TestClient(ag_app).get(
        f"/admin/v1/generation-audit/generations/{cx_generation_id}",
        params={"recovery_request_id": recovery_request["recovery_request_id"]},
        headers=service_headers("nex-oa", "nex-ag", trace_id, request_id),
    )
    ag_response.raise_for_status()

    evidence = {
        "trace_id": trace_id,
        "request_id": request_id,
        "cx_problem": failed.json(),
        "cx": cx_record,
        "cx_events": cx_events.json(),
        "ae_recovery": recovery_request,
        "ag": ag_response.json(),
    }
    evidence["assertions"] = assert_recovery_evidence(evidence)
    return evidence


def assert_recovery_evidence(evidence: dict[str, Any]) -> dict[str, bool]:
    trace_id = evidence["trace_id"]
    cx_generation_id = evidence["cx"]["cx_generation_id"]
    recovery_request_id = evidence["ae_recovery"]["recovery_request_id"]
    assertions = {
        "cx_problem_retryable": evidence["cx_problem"]["retryable"] is True,
        "cx_failed_record": evidence["cx"]["status"] == "FAILED",
        "cx_failure_code": evidence["cx"]["failure"]["failure_code"]
        == "mo.provider_timeout",
        "cx_failed_event": "generation.failed"
        in {event["event_type"] for event in evidence["cx_events"]["events"]},
        "ae_recovery_trace": evidence["ae_recovery"]["trace_id"] == trace_id,
        "ae_recovery_lineage": evidence["ae_recovery"]["cx_generation_id"]
        == cx_generation_id,
        "ae_recovery_action": evidence["ae_recovery"]["requested_action"] == "retry",
        "ae_recovery_dispatch": evidence["ae_recovery"]["dispatch"]["target_service"]
        == "nex-cx",
        "ag_trace": evidence["ag"]["trace_id"] == trace_id,
        "ag_recovery_lineage": evidence["ag"]["recovery_request_summary"][
            "recovery_request_id"
        ]
        == recovery_request_id,
        "ag_audit_action": evidence["ag"]["audit_event"]["action_type"] == "retry",
        "redaction_guard": RECOVERY_SMOKE_PROMPT not in json.dumps(
            evidence,
            ensure_ascii=False,
        ),
    }
    if not all(assertions.values()):
        raise AssertionError(f"recovery evidence mismatch: {assertions}")
    return assertions


def service_headers(
    service_id: str,
    audience: str,
    trace_id: str,
    request_id: str,
) -> dict[str, str]:
    token = issue_mock_service_token(service_id=service_id, audience=audience).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": service_id,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the generation recovery mock flow.")
    parser.add_argument("--summary", action="store_true", help="Print a short pass line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_generation_recovery_mock_flow()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.summary:
        print(
            "generation_recovery_mock_flow=pass "
            f"trace_id={evidence['trace_id']} "
            f"cx={evidence['cx']['cx_generation_id']} "
            f"recovery={evidence['ae_recovery']['recovery_request_id']} "
            f"action={evidence['ae_recovery']['requested_action']} "
            f"ag_action={evidence['ag']['audit_event']['action_type']}"
        )
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
