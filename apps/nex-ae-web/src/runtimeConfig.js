import {
  AE_WEB_CLIENT_MODES
} from "./clientRegistry.js";

export const AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION = "ae_web_runtime_config.v1";
export const AE_WEB_RUNTIME_CONFIG_ELEMENT_ID = "ae-web-runtime-config";

const DEFAULT_FEATURES = {
  document_detail_enabled: true,
  upload_submit_enabled: true,
  retrieval_submit_enabled: true,
  fetch_clients_enabled: false
};

const TOP_LEVEL_FIELDS = new Set([
  "runtime_config_schema_version",
  "client_mode",
  "clientMode",
  "ae_base_url",
  "aeBaseUrl",
  "features"
]);

const FEATURE_FIELDS = new Set(Object.keys(DEFAULT_FEATURES));

export class RuntimeConfigError extends Error {
  constructor(message, { status = "RUNTIME_CONFIG_INVALID" } = {}) {
    super(message);
    this.name = "RuntimeConfigError";
    this.status = status;
  }
}

export function loadRuntimeConfig({
  documentRef = globalThis.document,
  windowRef = globalThis
} = {}) {
  const inlineConfig = readInlineRuntimeConfig(documentRef);
  const globalConfig = isObject(windowRef?.__NEX_AE_WEB_CONFIG__)
    ? windowRef.__NEX_AE_WEB_CONFIG__
    : {};

  return normalizeRuntimeConfig({
    ...inlineConfig,
    ...globalConfig
  });
}

export function normalizeRuntimeConfig(config = {}) {
  if (!isObject(config)) {
    throw new RuntimeConfigError("Runtime config must be an object.", {
      status: "RUNTIME_CONFIG_OBJECT_INVALID"
    });
  }
  assertSupportedFields(config, TOP_LEVEL_FIELDS, "runtime_config");

  const clientMode = config.client_mode || config.clientMode || "mock";
  if (!AE_WEB_CLIENT_MODES.includes(clientMode)) {
    throw new RuntimeConfigError("Unsupported runtime client mode.", {
      status: "RUNTIME_CLIENT_MODE_UNSUPPORTED"
    });
  }

  const features = normalizeFeatures(config.features || {});
  if (clientMode === "fetch" && !features.fetch_clients_enabled) {
    throw new RuntimeConfigError("Fetch client mode requires an explicit feature flag.", {
      status: "FETCH_MODE_NOT_ENABLED"
    });
  }

  return {
    runtime_config_schema_version: AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION,
    clientMode,
    aeBaseUrl: normalizeAeBaseUrl(config.ae_base_url ?? config.aeBaseUrl ?? ""),
    features,
    metadata: {
      browserCredentialIncluded: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false
    }
  };
}

export function buildRuntimeConfigSummary(config) {
  const normalized =
    config?.runtime_config_schema_version === AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION
      ? config
      : normalizeRuntimeConfig(config);
  return {
    runtime_config_schema_version: normalized.runtime_config_schema_version,
    client_mode: normalized.clientMode,
    ae_base_url: normalized.aeBaseUrl,
    features: normalized.features,
    metadata: normalized.metadata
  };
}

function readInlineRuntimeConfig(documentRef) {
  const element = documentRef?.getElementById?.(AE_WEB_RUNTIME_CONFIG_ELEMENT_ID);
  if (!element) return {};
  const source = element.textContent?.trim();
  if (!source) return {};
  try {
    const parsed = JSON.parse(source);
    if (!isObject(parsed)) {
      throw new RuntimeConfigError("Inline runtime config must be an object.", {
        status: "RUNTIME_CONFIG_OBJECT_INVALID"
      });
    }
    return parsed;
  } catch (error) {
    if (error instanceof RuntimeConfigError) throw error;
    throw new RuntimeConfigError("Inline runtime config JSON is invalid.", {
      status: "RUNTIME_CONFIG_JSON_INVALID"
    });
  }
}

function normalizeFeatures(features) {
  if (!isObject(features)) {
    throw new RuntimeConfigError("features must be an object.", {
      status: "RUNTIME_FEATURES_INVALID"
    });
  }
  assertSupportedFields(features, FEATURE_FIELDS, "features");

  const normalized = { ...DEFAULT_FEATURES };
  for (const [key, value] of Object.entries(features)) {
    if (typeof value !== "boolean") {
      throw new RuntimeConfigError("Feature flags must be boolean.", {
        status: "RUNTIME_FEATURE_INVALID"
      });
    }
    normalized[key] = value;
  }
  return normalized;
}

function normalizeAeBaseUrl(value) {
  if (value == null || value === "") return "";
  if (typeof value !== "string") {
    throw new RuntimeConfigError("AE base URL must be a string.", {
      status: "AE_BASE_URL_INVALID"
    });
  }

  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  if (trimmed.startsWith("/")) return trimmed;

  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new RuntimeConfigError("AE base URL is invalid.", {
      status: "AE_BASE_URL_INVALID"
    });
  }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new RuntimeConfigError("AE base URL is not browser safe.", {
      status: "AE_BASE_URL_UNSAFE"
    });
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/+$/, "");
}

function assertSupportedFields(value, allowedFields, context) {
  for (const key of Object.keys(value)) {
    if (!allowedFields.has(key)) {
      throw new RuntimeConfigError(`${context} contains an unsupported field.`, {
        status: "RUNTIME_CONFIG_FIELD_UNSUPPORTED"
      });
    }
  }
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
