from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ag.readiness import register_readiness_routes
from nex_cx.generation import GenerationExecutionStore, register_generation_routes
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


@dataclass
class TestClientMoGenerationClient:
    client: TestClient
    last_response: dict[str, Any] | None = None

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/generations",
            json=payload,
            headers=service_headers("nex-cx", "nex-mo", trace_id, request_id),
        )
        response.raise_for_status()
        self.last_response = response.json()
        return self.last_response


@dataclass
class TestClientCxGenerationClient:
    client: TestClient
    last_response: dict[str, Any] | None = None

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/generations",
            json=payload,
            headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
        )
        response.raise_for_status()
        self.last_response = response.json()
        return self.last_response


class StaticReadinessStatusClient:
    def fetch_status(self, service_id: str, base_url: str) -> dict[str, Any]:
        return {
            "service_id": service_id,
            "base_url": base_url,
            "health_status": "HEALTHY",
            "readiness_status": "READY",
            "version": "0.0.0-smoke",
            "contract_catalog_version": "slice-0010",
            "observed_status": "READY",
            "failures": [],
        }


def run_traceable_mock_flow(trace_id: str = TRACE_ID) -> dict[str, Any]:
    request_id = REQUEST_ID

    mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
    register_mock_provider_routes(mo_app)
    mo_client = TestClientMoGenerationClient(TestClient(mo_app))

    cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(
        cx_app,
        store=GenerationExecutionStore(),
        mo_client=mo_client,
    )
    cx_client = TestClientCxGenerationClient(TestClient(cx_app))

    ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_chat_routes(
        ae_app,
        store=ChatInteractionStore(),
        cx_client=cx_client,
    )
    ae_response = TestClient(ae_app).post(
        "/api/v1/chat/interactions",
        json={
            "trace_id": trace_id,
            "user_message": "Summarize the first traceable mock flow.",
        },
        headers=service_headers("nex-oa", "nex-ae-api", trace_id, request_id),
    )
    ae_response.raise_for_status()

    ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_readiness_routes(
        ag_app,
        status_client=StaticReadinessStatusClient(),
        service_endpoints={
            service_id: f"http://127.0.0.1:{spec.default_port}"
            for service_id, spec in SERVICE_SPECS.items()
        },
    )
    ag_response = TestClient(ag_app).get(
        "/admin/v1/readiness/services",
        headers=service_headers("nex-oa", "nex-ag", trace_id, request_id),
    )
    ag_response.raise_for_status()

    evidence = {
        "trace_id": trace_id,
        "request_id": request_id,
        "ae": ae_response.json(),
        "cx": cx_client.last_response,
        "mo": mo_client.last_response,
        "ag": ag_response.json(),
    }
    evidence["assertions"] = assert_trace_evidence(evidence)
    return evidence


def assert_trace_evidence(evidence: dict[str, Any]) -> dict[str, bool]:
    trace_id = evidence["trace_id"]
    assertions = {
        "ae_trace": evidence["ae"]["trace_id"] == trace_id,
        "cx_trace": evidence["cx"]["trace_id"] == trace_id,
        "mo_trace": evidence["mo"]["runtime_metadata"]["trace_id"] == trace_id,
        "ag_trace": evidence["ag"]["trace_id"] == trace_id,
    }
    if not all(assertions.values()):
        raise AssertionError(f"trace evidence mismatch: {assertions}")
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
    parser = argparse.ArgumentParser(description="Run the first traceable mock flow.")
    parser.add_argument("--summary", action="store_true", help="Print a short pass line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_traceable_mock_flow()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.summary:
        print(
            "traceable_mock_flow=pass "
            f"trace_id={evidence['trace_id']} "
            f"ae={evidence['ae']['interaction_id']} "
            f"cx={evidence['cx']['cx_generation_id']} "
            f"mo={evidence['mo']['mo_generation_id']} "
            f"ag_services={evidence['ag']['summary']['total']}"
        )
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
