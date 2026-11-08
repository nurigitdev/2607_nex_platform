import {
  buildRuntimeConfigSummary,
  normalizeRuntimeConfig,
} from "../../runtimeConfig.js";

import type {
  RuntimeConfigInput,
  RuntimeProjection,
} from "../domain/runtime";

export function projectRuntimeConfig(
  input: RuntimeConfigInput = {},
): RuntimeProjection {
  const summary = buildRuntimeConfigSummary(normalizeRuntimeConfig(input));

  return Object.freeze({
    schemaVersion: summary.runtime_config_schema_version,
    clientMode: summary.client_mode,
    aeBaseUrl: summary.ae_base_url,
    features: Object.freeze({ ...summary.features }),
    metadata: Object.freeze({ ...summary.metadata }),
  });
}
