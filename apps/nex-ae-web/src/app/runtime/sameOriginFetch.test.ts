import { describe, expect, it, vi } from "vitest";

import {
  BrowserRequestBoundaryError,
  assertSameOriginAeRequest,
  createSameOriginAeFetch,
} from "./sameOriginFetch";

const ORIGIN = "https://nex.example.test";

describe("same-origin AE request boundary", () => {
  it("admits relative and same-origin AE facade requests", () => {
    expect(assertSameOriginAeRequest("/ae-api/api/v1/auth/session", ORIGIN).href)
      .toBe(`${ORIGIN}/ae-api/api/v1/auth/session`);
    expect(assertSameOriginAeRequest(`${ORIGIN}/ae-api`, ORIGIN).pathname)
      .toBe("/ae-api");
  });

  it.each([
    ["https://other.example.test/ae-api/api/v1/auth/session", "CROSS_ORIGIN_REQUEST_BLOCKED"],
    ["http://127.0.0.1:8101/api/v1/auth/session", "CROSS_ORIGIN_REQUEST_BLOCKED"],
    ["/api/v1/auth/session", "NON_AE_REQUEST_BLOCKED"],
    ["/ae-api-bypass/api/v1/auth/session", "NON_AE_REQUEST_BLOCKED"],
  ])("rejects a request outside the facade: %s", (url, expectedStatus) => {
    expect(() => assertSameOriginAeRequest(url, ORIGIN)).toThrowError(
      expect.objectContaining<Partial<BrowserRequestBoundaryError>>({
        status: expectedStatus,
      }),
    );
  });

  it("requires an explicit browser origin", () => {
    expect(() => assertSameOriginAeRequest("/ae-api/status", "")).toThrowError(
      expect.objectContaining<Partial<BrowserRequestBoundaryError>>({
        status: "BROWSER_ORIGIN_REQUIRED",
      }),
    );
  });

  it("delegates only admitted requests to fetch", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 }));
    const guardedFetch = createSameOriginAeFetch({
      fetchImpl: fetchImpl as typeof globalThis.fetch,
      browserOrigin: ORIGIN,
    });

    await guardedFetch("/ae-api/api/v1/documents", { method: "GET" });
    expect(fetchImpl).toHaveBeenCalledOnce();

    expect(() => guardedFetch("https://provider.example.test/v1/chat/completions"))
      .toThrowError(expect.objectContaining({ status: "CROSS_ORIGIN_REQUEST_BLOCKED" }));
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("fails closed when fetch is unavailable", () => {
    expect(() => createSameOriginAeFetch({
      fetchImpl: null as unknown as typeof globalThis.fetch,
      browserOrigin: ORIGIN,
    }))
      .toThrowError(expect.objectContaining({ status: "FETCH_UNAVAILABLE" }));
  });
});
