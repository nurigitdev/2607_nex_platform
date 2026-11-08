import { describe, expect, it, vi } from "vitest";

import { createLegacyRuntimeBoundary } from "./runtimeBoundary";

describe("legacy runtime boundary", () => {
  it("reuses the existing mock client registry through a typed gateway", () => {
    const boundary = createLegacyRuntimeBoundary();

    expect(boundary.runtime.clientMode).toBe("mock");
    expect(boundary.clients.summary.clientMode).toBe("mock");
    expect(boundary.clients.summary.clients.approval).toBe("mock");
    expect(boundary.clients.summary.metadata.browserServiceTokenIncluded).toBe(
      false,
    );
  });

  it("reuses fetch clients only through an explicitly enabled runtime config", () => {
    const fetchImpl = vi.fn<typeof globalThis.fetch>();
    const boundary = createLegacyRuntimeBoundary({
      config: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: true },
      },
      fetchImpl,
    });

    expect(boundary.runtime.clientMode).toBe("fetch");
    expect(boundary.clients.summary.baseUrl).toBe("/ae-api");
    expect(boundary.clients.summary.clients.grounded_generation).toBe("fetch");
  });

  it("fails closed when fetch mode is not explicitly enabled", () => {
    expect(() =>
      createLegacyRuntimeBoundary({ config: { client_mode: "fetch" } }),
    ).toThrow("Fetch client mode requires an explicit feature flag");
  });
});
