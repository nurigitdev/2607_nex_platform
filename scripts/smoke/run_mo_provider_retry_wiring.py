#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_registry import ProviderRouteError  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    execute_remote_embedding_request,
    execute_remote_generation_request,
    execute_remote_rerank_request,
)


def _response_sequence(*responses):
    calls = []
    pending = iter(responses)

    def requester(*args, **kwargs):
        calls.append({"method": args[0], "timeout": kwargs.get("timeout")})
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        return response

    return requester, calls


def run_mo_provider_retry_wiring() -> dict[str, Any]:
    common = {
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://provider.invalid/rerank",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://provider.invalid/chat",
        "NEX_MO_RETRY_BASE_DELAY_SECONDS": "0",
    }
    embedding_requester, embedding_calls = _response_sequence(
        httpx.ConnectError("down"),
        httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}),
    )
    embedding = execute_remote_embedding_request(
        {"inputs": ["hello"]},
        environ=common,
        requester=embedding_requester,
    )
    rerank_requester, rerank_calls = _response_sequence(
        httpx.Response(503),
        httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]}),
    )
    rerank = execute_remote_rerank_request(
        {"query": "hello", "documents": ["document"]},
        environ=common,
        requester=rerank_requester,
    )
    generation_requester, generation_calls = _response_sequence(
        httpx.ConnectError("down"),
        httpx.Response(
            200,
            json={
                "id": "chatcmpl-safe",
                "choices": [
                    {"message": {"content": "answer"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        ),
    )
    generation = execute_remote_generation_request(
        {"prompt": "hello"},
        request_id="request-safe",
        trace_id="trace-safe",
        environ=common,
        requester=generation_requester,
    )
    ambiguous_calls = 0

    def ambiguous_requester(*args, **kwargs):
        nonlocal ambiguous_calls
        ambiguous_calls += 1
        raise httpx.ReadTimeout("ambiguous")

    try:
        execute_remote_generation_request(
            {"prompt": "hello"},
            request_id="request-ambiguous",
            trace_id="trace-ambiguous",
            environ=common,
            requester=ambiguous_requester,
        )
        ambiguous_kind = None
    except ProviderRouteError as exc:
        ambiguous_kind = exc.failure_kind
    checks = {
        "embedding_retry_succeeded": len(embedding_calls) == 2
        and len(embedding["data"]) == 1,
        "reranking_retry_succeeded": len(rerank_calls) == 2
        and len(rerank["results"]) == 1,
        "generation_connect_retry_succeeded": len(generation_calls) == 2
        and generation["output"]["text"] == "answer",
        "generation_ambiguous_not_retried": ambiguous_calls == 1
        and ambiguous_kind == "read_timeout",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_retry_wiring.v1",
        "slice": "1146",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_retry_wiring_failed",
        "checks": checks,
        "summary": {
            "capability_count": 3,
            "successful_retry_count": 3,
            "ambiguous_generation_attempt_count": ambiguous_calls,
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1147",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_retry_wiring="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"recovered={summary.get('successful_retry_count', 0)} "
        f"ambiguous_attempts={summary.get('ambiguous_generation_attempt_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_retry_wiring()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
