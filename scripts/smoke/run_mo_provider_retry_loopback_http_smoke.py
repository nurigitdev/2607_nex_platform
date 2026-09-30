#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.remote_provider import (  # noqa: E402
    execute_remote_embedding_request,
    execute_remote_generation_request,
    execute_remote_rerank_request,
    list_remote_provider_telemetry,
    reset_remote_provider_telemetry,
)


PATHS = {
    "embedding": "/v1/embeddings",
    "reranking": "/v1/rerank",
    "generation": "/v1/chat/completions",
}


def run_mo_provider_retry_loopback_http_smoke() -> dict[str, Any]:
    server = _LoopbackProviderServer()
    server.start()
    reset_remote_provider_telemetry()
    try:
        env = _loopback_environment(server.port)
        embedding = execute_remote_embedding_request(
            {"inputs": ["resilience"]},
            environ=env,
        )
        reranking = execute_remote_rerank_request(
            {"query": "resilience", "documents": ["bounded retry"], "top_n": 1},
            environ=env,
        )
        generation = execute_remote_generation_request(
            {"prompt": "Return a short resilience acknowledgement."},
            request_id="request-1149",
            trace_id="trace-1149",
            environ=env,
        )
        telemetry = {
            item["capability"]: item
            for item in list_remote_provider_telemetry(environ=env)
        }
        counts = Counter(record["capability"] for record in server.records)
        checks = {
            "real_http_two_attempts_each": counts
            == {"embedding": 2, "reranking": 2, "generation": 2},
            "authorization_present_not_captured": all(
                record["authorization_present"] for record in server.records
            ),
            "canonical_request_shapes_seen": server.request_shapes()
            == {
                "embedding": ["input", "model"],
                "reranking": ["documents", "model", "query", "top_n"],
                "generation": [
                    "max_tokens",
                    "messages",
                    "model",
                    "stream",
                    "temperature",
                ],
            },
            "normalized_results_returned": (
                embedding["data"][0]["embedding"] == [0.25, 0.75]
                and reranking["results"][0]["score"] == 0.95
                and generation["output"]["text"] == "resilience-ok"
            ),
            "retry_telemetry_complete": all(
                item["request_count"] == 1
                and item["attempt_count"] == 2
                and item["retry_count"] == 1
                for item in telemetry.values()
            ),
            "throttle_retry_after_observed": telemetry["reranking"][
                "last_retry_failure_kind"
            ]
            == "throttled"
            and telemetry["reranking"]["last_retry_delay_ms"] == 0,
        }
        passed = all(checks.values())
        evidence = {
            "evidence_schema_version": "mo_provider_retry_loopback_http.v1",
            "slice": "1149",
            "status": "PASS" if passed else "FAIL",
            "failure_code": None if passed else "mo_provider_retry_loopback_failed",
            "checks": checks,
            "observations": {
                "attempt_counts": dict(sorted(counts.items())),
                "authorization_present_count": sum(
                    record["authorization_present"] for record in server.records
                ),
                "retry_counts": {
                    capability: telemetry[capability]["retry_count"]
                    for capability in sorted(telemetry)
                },
            },
            "summary": {
                "capability_count": len(counts),
                "http_request_count": len(server.records),
                "passed_check_count": sum(checks.values()),
                "check_count": len(checks),
            },
            "next_slice": "1150",
        }
        _assert_redacted(evidence, server.port)
        return evidence
    finally:
        server.stop()


class _LoopbackProviderServer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.attempts: Counter[str] = Counter()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="mo-provider-retry-loopback-smoke",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def request_shapes(self) -> dict[str, list[str]]:
        shapes: dict[str, list[str]] = {}
        for record in self.records:
            shapes.setdefault(record["capability"], record["body_keys"])
        return shapes

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                capability = _capability_for_path(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                owner.attempts[capability] += 1
                owner.records.append(
                    {
                        "capability": capability,
                        "authorization_present": bool(self.headers.get("Authorization")),
                        "body_keys": sorted(payload),
                    }
                )
                if owner.attempts[capability] == 1:
                    status = 429 if capability == "reranking" else 503
                    headers = {"Retry-After": "0"} if status == 429 else {}
                    self._respond(status, {"error": "transient"}, headers)
                    return
                self._respond(200, _success_payload(capability), {})

            def _respond(
                self,
                status: int,
                payload: Mapping[str, Any],
                headers: Mapping[str, str],
            ) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: Any) -> None:
                return None

        return Handler


def _loopback_environment(port: int) -> dict[str, str]:
    base = f"http://127.0.0.1:{port}"
    return {
        "NEX_MO_REMOTE_EMBEDDING_URL": f"{base}{PATHS['embedding']}",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-loopback-key",
        "NEX_MO_REMOTE_RERANKER_URL": f"{base}{PATHS['reranking']}",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "private-loopback-key",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": f"{base}{PATHS['generation']}",
        "NEX_MO_VLLM_API_KEY": "private-loopback-key",
        "NEX_MO_RETRY_BASE_DELAY_SECONDS": "0",
        "NEX_MO_RETRY_MAX_DELAY_SECONDS": "0",
    }


def _capability_for_path(path: str) -> str:
    for capability, expected in PATHS.items():
        if path == expected:
            return capability
    raise ValueError("unexpected loopback provider path")


def _success_payload(capability: str) -> dict[str, Any]:
    if capability == "embedding":
        return {"data": [{"index": 0, "embedding": [0.25, 0.75]}]}
    if capability == "reranking":
        return {"results": [{"index": 0, "relevance_score": 0.95}]}
    return {
        "id": "completion-1149",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "resilience-ok"},
                "finish_reason": "stop",
            }
        ],
    }


def _assert_redacted(evidence: Mapping[str, Any], port: int) -> None:
    serialized = json.dumps(evidence, sort_keys=True)
    for token in (str(port), "private-loopback-key", "Authorization", "127.0.0.1"):
        if token in serialized:
            raise ValueError("loopback retry evidence leaked a private runtime value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_retry_loopback_http="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"requests={summary.get('http_request_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_retry_loopback_http_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
