from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nex_runtime.problem import problem_response


def build_problem_app() -> FastAPI:
    app = FastAPI()

    @app.get("/problem", response_model=None)
    def get_problem(request: Request):
        return problem_response(
            request,
            status_code=429,
            error_code="TOO_MANY_REQUESTS",
            title="Too many requests",
            detail="Retry later.",
            retryable=True,
            details={"retry_after_seconds": 3},
        )

    return app


def test_problem_response_uses_supplied_trace_headers() -> None:
    client = TestClient(build_problem_app())

    response = client.get(
        "/problem",
        headers={
            "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["error_code"] == "TOO_MANY_REQUESTS"
    assert payload["request_id"] == "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert payload["details"] == {"retry_after_seconds": 3}


def test_problem_response_generates_missing_trace_refs() -> None:
    client = TestClient(build_problem_app())

    payload = client.get("/problem").json()

    assert len(payload["request_id"]) == 36
    assert len(payload["trace_id"]) == 32


def test_problem_response_replaces_malformed_traceparent() -> None:
    client = TestClient(build_problem_app())

    payload = client.get(
        "/problem",
        headers={
            "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
            "traceparent": "not-a-w3c-traceparent",
        },
    ).json()

    assert payload["request_id"] == "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
    assert len(payload["trace_id"]) == 32
    assert payload["trace_id"] != "not-a-w3c-traceparent"
