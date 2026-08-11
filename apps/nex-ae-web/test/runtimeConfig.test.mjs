import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_RUNTIME_CONFIG_ELEMENT_ID,
  AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION,
  RuntimeConfigError,
  buildRuntimeConfigSummary,
  loadRuntimeConfig,
  normalizeRuntimeConfig
} from "../src/runtimeConfig.js";

function documentWithConfig(textContent) {
  return {
    getElementById(id) {
      if (id !== AE_WEB_RUNTIME_CONFIG_ELEMENT_ID) return null;
      return { textContent };
    }
  };
}

describe("AE Web runtime config", () => {
  it("loads safe default mock configuration when no source is present", () => {
    const config = loadRuntimeConfig({
      documentRef: { getElementById: () => null },
      windowRef: {}
    });
    const summary = buildRuntimeConfigSummary(config);

    assert.equal(config.runtime_config_schema_version, AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION);
    assert.equal(config.clientMode, "mock");
    assert.equal(config.aeBaseUrl, "");
    assert.equal(config.features.fetch_clients_enabled, false);
    assert.equal(config.features.document_detail_enabled, true);
    assert.deepEqual(summary.metadata, {
      browserCredentialIncluded: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false
    });
    assert.doesNotMatch(JSON.stringify(summary), /secret|postgres|provider_url|api_key|service_token|\/data\/nex-platform/);
  });

  it("loads inline JSON and allows global overrides for fetch mode", () => {
    const documentRef = documentWithConfig(
      JSON.stringify({
        runtime_config_schema_version: AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION,
        client_mode: "mock",
        ae_base_url: "/ae-api",
        features: {
          upload_submit_enabled: false
        }
      })
    );
    const windowRef = {
      __NEX_AE_WEB_CONFIG__: {
        client_mode: "fetch",
        ae_base_url: "https://ae.local/",
        features: {
          document_detail_enabled: true,
          upload_submit_enabled: true,
          retrieval_submit_enabled: true,
          fetch_clients_enabled: true
        }
      }
    };

    const config = loadRuntimeConfig({ documentRef, windowRef });

    assert.equal(config.clientMode, "fetch");
    assert.equal(config.aeBaseUrl, "https://ae.local");
    assert.equal(config.features.fetch_clients_enabled, true);
    assert.equal(config.features.upload_submit_enabled, true);
  });

  it("normalizes same-origin base paths and boolean feature defaults", () => {
    const config = normalizeRuntimeConfig({
      clientMode: "mock",
      aeBaseUrl: "/ae-api/",
      features: {
        retrieval_submit_enabled: false
      }
    });

    assert.equal(config.aeBaseUrl, "/ae-api");
    assert.equal(config.features.retrieval_submit_enabled, false);
    assert.equal(config.features.upload_submit_enabled, true);
  });

  it("rejects malformed JSON, unsupported fields, and unsafe fetch mode", () => {
    assert.throws(
      () =>
        loadRuntimeConfig({
          documentRef: documentWithConfig("{bad"),
          windowRef: {}
        }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "RUNTIME_CONFIG_JSON_INVALID"
    );
    assert.throws(
      () => normalizeRuntimeConfig({ client_mode: "live" }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "RUNTIME_CLIENT_MODE_UNSUPPORTED"
    );
    assert.throws(
      () => normalizeRuntimeConfig({ client_mode: "mock", credential: "secret" }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "RUNTIME_CONFIG_FIELD_UNSUPPORTED"
    );
    assert.throws(
      () =>
        normalizeRuntimeConfig({
          client_mode: "fetch",
          features: { fetch_clients_enabled: false }
        }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "FETCH_MODE_NOT_ENABLED"
    );
  });

  it("rejects invalid feature values and unsafe AE base URLs", () => {
    assert.throws(
      () => normalizeRuntimeConfig({ features: "bad" }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "RUNTIME_FEATURES_INVALID"
    );
    assert.throws(
      () => normalizeRuntimeConfig({ features: { unknown_flag: true } }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "RUNTIME_CONFIG_FIELD_UNSUPPORTED"
    );
    assert.throws(
      () => normalizeRuntimeConfig({ features: { upload_submit_enabled: "yes" } }),
      error =>
        error instanceof RuntimeConfigError &&
        error.status === "RUNTIME_FEATURE_INVALID"
    );
    assert.throws(
      () => normalizeRuntimeConfig({ ae_base_url: "ftp://ae.local" }),
      error =>
        error instanceof RuntimeConfigError && error.status === "AE_BASE_URL_UNSAFE"
    );
    assert.throws(
      () => normalizeRuntimeConfig({ ae_base_url: "https://user:pass@ae.local" }),
      error =>
        error instanceof RuntimeConfigError && error.status === "AE_BASE_URL_UNSAFE"
    );
  });
});
