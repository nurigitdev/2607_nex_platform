import { createLegacyClientGateway } from "../api/legacyClientGateway";
import type { RuntimeConfigInput } from "../domain/runtime";
import { projectRuntimeConfig } from "./runtimeConfigAdapter";

export function createLegacyRuntimeBoundary({
  config = {},
  fetchImpl,
}: {
  readonly config?: RuntimeConfigInput;
  readonly fetchImpl?: typeof globalThis.fetch;
} = {}) {
  const runtime = projectRuntimeConfig(config);
  const clients = createLegacyClientGateway({
    mode: runtime.clientMode,
    baseUrl: runtime.aeBaseUrl,
    fetchImpl,
  });

  return Object.freeze({ runtime, clients });
}
