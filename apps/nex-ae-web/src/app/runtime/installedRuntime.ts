import { createLegacyClientGateway } from "../api/legacyClientGateway";
import type { RuntimeProjection } from "../domain/runtime";
import {
  loadProjectedRuntimeConfig,
} from "../legacyAdapters/runtimeConfigAdapter";
import {
  createModernSessionClient,
  type SessionClientPort,
} from "../legacyAdapters/sessionAdapter";
import { createSameOriginAeFetch } from "./sameOriginFetch";

export const MODERN_TENANT_META_NAME = "nex-ae-tenant-id";

export interface InstalledBrowserRuntime {
  readonly config: RuntimeProjection;
  readonly tenantId: string;
  readonly sessionClient: SessionClientPort;
  readonly clients: ReturnType<typeof createLegacyClientGateway>;
}

export class InstalledRuntimeError extends Error {
  readonly status: string;

  constructor(message: string, status: string) {
    super(message);
    this.name = "InstalledRuntimeError";
    this.status = status;
  }
}

export function createInstalledBrowserRuntime({
  documentRef = globalThis.document,
  windowRef = globalThis,
  fetchImpl = globalThis.fetch,
}: {
  readonly documentRef?: Document;
  readonly windowRef?: typeof globalThis;
  readonly fetchImpl?: typeof globalThis.fetch;
} = {}): InstalledBrowserRuntime {
  if (!documentRef?.getElementById("ae-web-runtime-config")) {
    throw new InstalledRuntimeError("Runtime config is required.", "RUNTIME_CONFIG_REQUIRED");
  }
  const config = loadProjectedRuntimeConfig({ documentRef, windowRef });
  assertInstalledRuntimeConfig(config);
  const tenantId = readTenantId(documentRef);
  const guardedFetch = createSameOriginAeFetch({
    fetchImpl,
    browserOrigin: windowRef.location?.origin,
  });

  return Object.freeze({
    config,
    tenantId,
    sessionClient: createModernSessionClient({
      mode: "fetch",
      baseUrl: config.aeBaseUrl,
      fetchImpl: guardedFetch,
    }),
    clients: createLegacyClientGateway({
      mode: "fetch",
      baseUrl: config.aeBaseUrl,
      fetchImpl: guardedFetch,
    }),
  });
}

export function assertInstalledRuntimeConfig(config: RuntimeProjection) {
  if (config.clientMode !== "fetch") {
    throw new InstalledRuntimeError("Installed runtime must use fetch clients.", "MOCK_RUNTIME_BLOCKED");
  }
  if (!config.features.fetch_clients_enabled) {
    throw new InstalledRuntimeError("Fetch clients must be explicitly enabled.", "FETCH_FLAG_REQUIRED");
  }
  if (config.aeBaseUrl !== "/ae-api") {
    throw new InstalledRuntimeError("Installed runtime must use the AE facade.", "AE_FACADE_REQUIRED");
  }
}

function readTenantId(documentRef: Document) {
  const value = documentRef
    .querySelector<HTMLMetaElement>(`meta[name="${MODERN_TENANT_META_NAME}"]`)
    ?.content.trim();
  if (!value) {
    throw new InstalledRuntimeError("Tenant configuration is required.", "TENANT_CONFIG_REQUIRED");
  }
  return value;
}
