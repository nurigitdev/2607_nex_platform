import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION,
  ClientRegistryError,
  buildClientRegistrySummary,
  createAeWebClients
} from "../src/clientRegistry.js";

function documents() {
  return [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      ownerScope: {
        tenantId: "tenant-local",
        ownerUserId: "owner-local"
      },
      processingStatus: "COMPLETED",
      summaryStatus: "READY"
    }
  ];
}

describe("AE Web client registry", () => {
  it("builds a safe mock client registry for all browser adapters", () => {
    const registry = createAeWebClients({
      mode: "mock",
      documents: documents()
    });
    const summary = buildClientRegistrySummary(registry);

    assert.equal(
      registry.client_registry_schema_version,
      AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION
    );
    assert.equal(registry.clientMode, "mock");
    assert.equal(registry.baseUrl, "");
    assert.equal(registry.documentDetailClient.clientMode, "mock");
    assert.equal(registry.uploadClient.clientMode, "mock");
    assert.equal(registry.retrievalClient.clientMode, "mock");
    assert.equal(summary.clients.document_detail, "mock");
    assert.deepEqual(summary.metadata, {
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false,
      rawSourceIncluded: false
    });
    assert.doesNotMatch(JSON.stringify(summary), /service_token|api_key|database_url|provider_url/);
  });

  it("builds fetch clients with normalized base URL and shared fetch implementation", async () => {
    const calls = [];
    const registry = createAeWebClients({
      mode: "fetch",
      baseUrl: "https://ae.local/",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              projection_schema_version: "ae_document_detail_projection.v1",
              tenant_id: "tenant-local",
              owner_user_id: "owner-local",
              document: {
                document_id: "doc-001",
                filename: "29_mvp_srs.md",
                status: {},
                summary: { summary_available: false }
              },
              cx: { source_kind: "ae-facade" }
            };
          }
        };
      }
    });

    await registry.documentDetailClient.getDocumentDetail("doc-001");
    const summary = buildClientRegistrySummary(registry);

    assert.equal(registry.clientMode, "fetch");
    assert.equal(registry.baseUrl, "https://ae.local");
    assert.equal(calls[0].url, "https://ae.local/api/v1/documents/doc-001");
    assert.equal(summary.base_url, "https://ae.local");
    assert.equal(summary.clients.upload, "fetch");
    assert.equal(summary.clients.retrieval, "fetch");
  });

  it("rejects unsupported client modes and invalid base URLs", () => {
    assert.throws(
      () => createAeWebClients({ mode: "live" }),
      error =>
        error instanceof ClientRegistryError &&
        error.status === "CLIENT_MODE_UNSUPPORTED"
    );
    assert.throws(
      () => createAeWebClients({ mode: "fetch", baseUrl: 123, fetchImpl: async () => ({}) }),
      error =>
        error instanceof ClientRegistryError &&
        error.status === "BASE_URL_INVALID"
    );
    assert.throws(
      () => buildClientRegistrySummary({}),
      error =>
        error instanceof ClientRegistryError &&
        error.status === "CLIENT_REGISTRY_SUMMARY_INVALID"
    );
  });
});
