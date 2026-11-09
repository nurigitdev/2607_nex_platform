import { describe, expect, it, vi } from "vitest";

import { createOperationsClient, OperationsClientError, projectOperationsSummary } from "./operationsClientPort";

describe("operations client port", () => {
  it("projects only safe service, runtime, and route fields", () => {
    const projection = projectOperationsSummary(summaryPayload({
      private_debug: { database_url: "postgresql://hidden", provider_endpoint: "http://hidden" },
    }));
    expect(projection.services[0]).toEqual({ serviceId: "nex-ae-api", healthStatus: "HEALTHY", readinessStatus: "READY", version: "2.1.0" });
    expect(JSON.stringify(projection)).not.toMatch(/database_url|provider_endpoint|hidden/i);
  });

  it("uses the same-origin operations facade without service credentials", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify(summaryPayload()), { status: 200, headers: { "Content-Type": "application/json" } }));
    const client = createOperationsClient({ mode: "fetch", baseUrl: "/ae-api", fetchImpl });
    await expect(client.getSummary()).resolves.toEqual(expect.objectContaining({ overallStatus: "READY" }));
    expect(fetchImpl).toHaveBeenCalledWith("/ae-api/api/v1/web/operations/summary", {
      credentials: "include", headers: { Accept: "application/json" },
    });
    expect(JSON.stringify(fetchImpl.mock.calls)).not.toMatch(/authorization|service-token/i);
  });

  it("maps forbidden, unavailable, network, and malformed responses", async () => {
    const forbidden = createOperationsClient({ mode: "fetch", fetchImpl: vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_code: "AE_WEB_OPERATIONS_FORBIDDEN" }), { status: 403 })) });
    await expect(forbidden.getSummary()).rejects.toMatchObject({ statusCode: 403, retryable: false });

    const unavailable = createOperationsClient({ mode: "fetch", fetchImpl: vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_code: "AE_WEB_OPERATIONS_UNAVAILABLE", retryable: true }), { status: 503 })) });
    await expect(unavailable.getSummary()).rejects.toMatchObject({ statusCode: 503, retryable: true });

    const network = createOperationsClient({ mode: "fetch", fetchImpl: vi.fn().mockRejectedValue(new Error("private")) });
    await expect(network.getSummary()).rejects.toMatchObject({ status: "NETWORK_ERROR", retryable: true });

    expect(() => projectOperationsSummary({ operations_summary_schema_version: "wrong" })).toThrow(OperationsClientError);
    expect(() => projectOperationsSummary(summaryPayload({ safe_routes: [{ route_id: "unsafe", method: "GET", path: "http://127.0.0.1:8102/health" }] }))).toThrow(/안전하지/);
    expect(() => createOperationsClient({ mode: "fetch" })).toThrow(/Fetch/);
  });

  it("serves deterministic mock diagnostics", async () => {
    const client = createOperationsClient({ mode: "mock" });
    const summary = await client.getSummary();
    expect(summary.runtime.agentRuntimeStatus).toBe("AVAILABLE");
    expect(summary.routes[0].path).toBe("/api/v1/web/operations/summary");
  });
});

function summaryPayload(overrides: Record<string, unknown> = {}) {
  return {
    operations_summary_schema_version: "ae_web_operations_summary.v1",
    overall_status: "READY",
    services: [{ service_id: "nex-ae-api", health_status: "HEALTHY", readiness_status: "READY", version: "2.1.0" }],
    runtime: { database_status: "AVAILABLE", agent_runtime_status: "AVAILABLE", provider_route_status: "CONFIGURED" },
    safe_routes: [{ route_id: "ae-web-operations-summary", method: "GET", path: "/api/v1/web/operations/summary" }],
    ...overrides,
  };
}
