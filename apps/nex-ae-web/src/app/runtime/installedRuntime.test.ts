import { describe, expect, it, vi } from "vitest";

import { createInstalledBrowserRuntime } from "./installedRuntime";

const VALID_CONFIG = {
  client_mode: "fetch",
  ae_base_url: "/ae-api",
  features: { fetch_clients_enabled: true },
};

function runtimeDocument({
  config = VALID_CONFIG,
  tenantId = "VO00",
  includeConfig = true,
}: {
  readonly config?: unknown;
  readonly tenantId?: string | null;
  readonly includeConfig?: boolean;
} = {}) {
  const runtimeConfig = includeConfig
    ? `<script id="ae-web-runtime-config" type="application/json">${JSON.stringify(config)}</script>`
    : "";
  const tenant = tenantId === null
    ? ""
    : `<meta name="nex-ae-tenant-id" content="${tenantId}">`;
  return new DOMParser().parseFromString(
    `<!doctype html><html><head>${tenant}</head><body>${runtimeConfig}</body></html>`,
    "text/html",
  );
}

function createRuntime(options: Parameters<typeof runtimeDocument>[0] = {}) {
  return createInstalledBrowserRuntime({
    documentRef: runtimeDocument(options),
    windowRef: globalThis,
    fetchImpl: vi.fn(async () => new Response(null, { status: 204 })) as typeof globalThis.fetch,
  });
}

describe("installed browser runtime", () => {
  it("builds fetch-only clients behind the same-origin AE facade", () => {
    const runtime = createRuntime();

    expect(runtime.tenantId).toBe("VO00");
    expect(runtime.config).toMatchObject({
      clientMode: "fetch",
      aeBaseUrl: "/ae-api",
      features: { fetch_clients_enabled: true },
    });
    expect(runtime.clients.summary).toMatchObject({
      clientMode: "fetch",
      baseUrl: "/ae-api",
    });
  });

  it("rejects a missing installed runtime config", () => {
    expect(() => createRuntime({ includeConfig: false })).toThrowError(
      expect.objectContaining({ status: "RUNTIME_CONFIG_REQUIRED" }),
    );
  });

  it("rejects mock mode and disabled fetch clients", () => {
    expect(() => createRuntime({ config: { client_mode: "mock" } })).toThrowError(
      expect.objectContaining({ status: "MOCK_RUNTIME_BLOCKED" }),
    );
    expect(() => createRuntime({
      config: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: false },
      },
    })).toThrowError(expect.objectContaining({ status: "FETCH_MODE_NOT_ENABLED" }));
  });

  it.each([
    "https://nex.example.test/ae-api",
    "/api",
    "http://127.0.0.1:8101",
  ])("rejects a non-canonical AE facade binding: %s", aeBaseUrl => {
    expect(() => createRuntime({
      config: {
        ...VALID_CONFIG,
        ae_base_url: aeBaseUrl,
      },
    })).toThrowError(expect.objectContaining({ status: "AE_FACADE_REQUIRED" }));
  });

  it("requires a deployment-resolved tenant", () => {
    expect(() => createRuntime({ tenantId: null })).toThrowError(
      expect.objectContaining({ status: "TENANT_CONFIG_REQUIRED" }),
    );
    expect(() => createRuntime({ tenantId: "   " })).toThrowError(
      expect.objectContaining({ status: "TENANT_CONFIG_REQUIRED" }),
    );
  });

  it("rejects malformed or credential-bearing runtime config", () => {
    const malformed = runtimeDocument();
    const element = malformed.getElementById("ae-web-runtime-config");
    if (element) element.textContent = "{not-json";
    expect(() => createInstalledBrowserRuntime({
      documentRef: malformed,
      windowRef: globalThis,
      fetchImpl: vi.fn() as typeof globalThis.fetch,
    })).toThrowError(expect.objectContaining({ status: "RUNTIME_CONFIG_JSON_INVALID" }));

    expect(() => createRuntime({
      config: {
        ...VALID_CONFIG,
        service_token: "must-not-enter-the-browser",
      },
    })).toThrowError(expect.objectContaining({ status: "RUNTIME_CONFIG_FIELD_UNSUPPORTED" }));
  });
});
