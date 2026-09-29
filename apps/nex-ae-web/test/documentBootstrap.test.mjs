import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION,
  DocumentBootstrapError,
  buildDocumentBootstrapSummary,
  loadDocumentBootstrap,
  normalizeDocumentBootstrap
} from "../src/documentBootstrap.js";

const MAIN_SOURCE = new URL("../src/main.js", import.meta.url);

function fixture(overrides = {}) {
  return {
    schema_version: AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION,
    documents: [
      {
        document_id: "7d88f119-d9c7-4c8a-a310-c3eea6613f64",
        filename: "grounding.md",
        tenant_id: "tenant-1090",
        owner_user_id: "owner-1090",
        processing_status: "COMPLETED",
        extraction_status: "COMPLETED",
        summary_status: "READY",
        confidence_bucket: "HIGH",
        best_score: 0.91
      }
    ],
    ...overrides
  };
}

test("normalizes safe server-provided document metadata", () => {
  const result = normalizeDocumentBootstrap(fixture());
  assert.equal(result.documents[0].clientMode, "fetch");
  assert.equal(result.documents[0].sourceKind, "postgres-read");
  assert.equal(result.metadata.rawSourceIncluded, false);
  assert.deepEqual(buildDocumentBootstrapSummary(result), {
    schema_version: AE_WEB_DOCUMENT_BOOTSTRAP_SCHEMA_VERSION,
    document_count: 1,
    document_ids_present: true,
    metadata: result.metadata
  });
});

test("loads optional browser bootstrap and rejects unsafe shapes", () => {
  assert.equal(loadDocumentBootstrap({ windowRef: {} }), null);
  assert.equal(
    loadDocumentBootstrap({
      windowRef: { __NEX_AE_WEB_DOCUMENT_BOOTSTRAP__: fixture() }
    }).documents.length,
    1
  );
  assert.throws(
    () => normalizeDocumentBootstrap({ ...fixture(), provider_url: "hidden" }),
    error => error instanceof DocumentBootstrapError &&
      error.status === "DOCUMENT_BOOTSTRAP_FIELD_UNSUPPORTED"
  );
  assert.throws(
    () => normalizeDocumentBootstrap(fixture({ schema_version: "old" })),
    /unsupported/
  );
});

test("rejects empty, duplicate, and invalid document metadata", () => {
  assert.throws(() => normalizeDocumentBootstrap([]), /object/);
  assert.throws(
    () => normalizeDocumentBootstrap(fixture({ documents: [] })),
    /requires documents/
  );
  const duplicate = fixture();
  duplicate.documents.push({ ...duplicate.documents[0] });
  assert.throws(() => normalizeDocumentBootstrap(duplicate), /unique/);
  assert.throws(
    () => normalizeDocumentBootstrap(
      fixture({ documents: [{ ...fixture().documents[0], best_score: 2 }] })
    ),
    /score/
  );
  assert.throws(() => buildDocumentBootstrapSummary({}), /summary/);
});

test("main selects the first server-bootstrapped document before scope creation", async () => {
  const source = await readFile(fileURLToPath(MAIN_SOURCE), "utf8");
  assert.match(
    source,
    /selectedDocumentId:\s*documentBootstrap\?\.documents\[0\]\?\.documentId\s*\|\|\s*"doc-001"/
  );
});
