import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION,
  AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION,
  AE_ARTIFACT_RECORD_SCHEMA_VERSION,
  AE_WEB_ARTIFACT_EXPORT_REQUEST_SCHEMA_VERSION,
  AE_WEB_ARTIFACT_EXPORT_SURFACE_SCHEMA_VERSION,
  AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
  ArtifactClientError,
  artifactDetailRoute,
  artifactFileDownloadRoute,
  artifactFileMetadataRoute,
  artifactFilePreviewRoute,
  artifactRenderJobRoute,
  artifactVersionsRoute,
  buildArtifactExportRequest,
  buildArtifactExportSummary,
  buildArtifactExportSurface,
  buildArtifactClientSummary,
  buildArtifactDownloadSurface,
  buildArtifactPreviewSurface,
  buildArtifactSurfaceFromRecord,
  buildArtifactVersionsSurface,
  createFetchArtifactClient,
  createMockArtifactClient,
  findSensitiveArtifactClientKeys
} from "../src/artifactClient.js";

function artifactRecord(overrides = {}) {
  return {
    artifact_schema_version: AE_ARTIFACT_RECORD_SCHEMA_VERSION,
    artifact_id: "artifact-001",
    artifact_type: "generated_document",
    artifact_status: "READY",
    current_version_id: "artifact-version-001",
    chat_document_id: "chat-doc-001",
    interaction_id: "interaction-001",
    display_title: "Generated report",
    target_formats: ["MD", "HTML_PREVIEW"],
    source_refs: [
      {
        cx_generation_id: "cx-gen-001",
        structured_draft_content_hash: "c".repeat(64),
        retrieval_package_id: "cx-ret-001",
        evidence_ref_count: 2,
        quality_summary: {
          citation_status: "VALIDATED",
          citation_count: 2,
          grounding_required: true,
          retrieval_package_id: "cx-ret-001",
          evidence_ref_count: 2
        }
      }
    ],
    versions: [
      {
        artifact_version_id: "artifact-version-001",
        version_no: 1,
        source_content_hash: "c".repeat(64),
        artifact_content_hash: "e".repeat(64),
        rendered_formats: ["MD"]
      }
    ],
    files: [
      {
        artifact_file_id: "artifact-file-001",
        artifact_id: "artifact-001",
        artifact_version_id: "artifact-version-001",
        format: "MD",
        mime_type: "text/markdown",
        file_name: "generated-report.md",
        storage_ref: "ae://artifacts/artifact-001/versions/artifact-version-001/generated-report.md",
        file_size_bytes: 512,
        file_hash: "f".repeat(64),
        source_version_hash: "e".repeat(64)
      }
    ],
    links: [
      {
        artifact_link_id: "artifact-link-preview-001",
        artifact_file_id: "artifact-file-001",
        link_type: "preview",
        access_policy: "owner_only",
        link_route: "/api/v1/artifact-files/artifact-file-001/preview"
      },
      {
        artifact_link_id: "artifact-link-download-001",
        artifact_file_id: "artifact-file-001",
        link_type: "download",
        access_policy: "owner_only",
        link_route: "/api/v1/artifact-files/artifact-file-001/download"
      }
    ],
    ...overrides
  };
}

function previewPayload(overrides = {}) {
  return {
    preview_schema_version: AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION,
    artifact_file: artifactRecord().files[0],
    artifact_link: artifactRecord().links[0],
    content_type: "text/markdown",
    text_preview: "# Generated report\n\n요약 미리보기입니다.",
    truncated: false,
    ...overrides
  };
}

function downloadPayload(overrides = {}) {
  return {
    download_schema_version: AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION,
    artifact_file: artifactRecord().files[0],
    artifact_link: artifactRecord().links[1],
    download_file_name: "generated-report.md",
    content_type: "text/markdown",
    content_hash: "f".repeat(64),
    content: "# Generated report\n\n다운로드 본문입니다.",
    ...overrides
  };
}

function jsonResponse({ ok = true, status = 200, payload }) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

describe("AE Web artifact client adapter", () => {
  it("normalizes artifact records into browser-safe surfaces", () => {
    const surface = buildArtifactSurfaceFromRecord(artifactRecord(), {
      clientMode: "mock",
      route: "/api/v1/artifacts/artifact-001"
    });
    const summary = buildArtifactClientSummary(surface);

    assert.equal(
      surface.artifact_client_schema_version,
      AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION
    );
    assert.equal(surface.artifactId, "artifact-001");
    assert.equal(surface.artifactVersionId, "artifact-version-001");
    assert.equal(surface.primaryFormat, "MD");
    assert.deepEqual(surface.availableFormats, ["MD"]);
    assert.equal(
      surface.previewRoute,
      "/api/v1/artifact-files/artifact-file-001/preview"
    );
    assert.deepEqual(surface.downloadRoutes, {
      MD: "/api/v1/artifact-files/artifact-file-001/download"
    });
    assert.equal(surface.files[0].storage_ref, undefined);
    assert.equal(surface.qualitySummary.citationStatus, "VALIDATED");
    assert.equal(summary.content_included, false);
    assert.doesNotMatch(
      JSON.stringify(surface),
      /storage_ref|storage_path|service_token|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("supports mock record, versions, file, preview, and download readback", async () => {
    const client = createMockArtifactClient({
      artifacts: [artifactRecord()],
      previews: { "artifact-file-001": previewPayload({ truncated: true }) },
      downloads: { "artifact-file-001": downloadPayload() }
    });

    const artifact = await client.getArtifact("artifact-001");
    const versions = await client.listArtifactVersions("artifact-001");
    const file = await client.getArtifactFile("artifact-file-001");
    const preview = await client.previewArtifactFile("artifact-file-001");
    const download = await client.downloadArtifactFile("artifact-file-001");

    assert.equal(client.clientMode, "mock");
    assert.equal(artifact.clientMode, "mock");
    assert.equal(versions.versionCount, 1);
    assert.equal(file.fileName, "generated-report.md");
    assert.equal(preview.truncated, true);
    assert.match(preview.textPreview, /요약 미리보기/);
    assert.equal(download.content.includes("다운로드 본문"), true);
    assert.equal(download.metadata.contentIncluded, true);
    assert.equal(buildArtifactClientSummary(download).download_route_count, 1);
  });

  it("uses same-origin fetch routes for all artifact read paths", async () => {
    const calls = [];
    const client = createFetchArtifactClient({
      baseUrl: "https://ae.local",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        if (String(url).endsWith("/versions")) {
          return jsonResponse({
            payload: {
              artifact_id: "artifact-001",
              current_version_id: "artifact-version-001",
              versions: artifactRecord().versions
            }
          });
        }
        if (String(url).endsWith("/preview")) {
          return jsonResponse({ payload: previewPayload() });
        }
        if (String(url).endsWith("/download")) {
          return jsonResponse({ payload: downloadPayload() });
        }
        if (String(url).includes("/artifact-files/")) {
          return jsonResponse({ payload: artifactRecord().files[0] });
        }
        return jsonResponse({ payload: artifactRecord() });
      }
    });

    await client.getArtifact("artifact-001");
    await client.listArtifactVersions("artifact-001");
    await client.getArtifactFile("artifact-file-001");
    await client.previewArtifactFile("artifact-file-001");
    await client.downloadArtifactFile("artifact-file-001");

    assert.deepEqual(
      calls.map(call => call.url),
      [
        "https://ae.local/api/v1/artifacts/artifact-001",
        "https://ae.local/api/v1/artifacts/artifact-001/versions",
        "https://ae.local/api/v1/artifact-files/artifact-file-001",
        "https://ae.local/api/v1/artifact-files/artifact-file-001/preview",
        "https://ae.local/api/v1/artifact-files/artifact-file-001/download"
      ]
    );
    assert.equal(calls.every(call => call.options.credentials === "same-origin"), true);
    assert.equal(calls.every(call => call.options.headers.Accept === "application/json"), true);
  });

  it("maps routes and fallback artifact metadata consistently", () => {
    const draft = buildArtifactSurfaceFromRecord(
      artifactRecord({
        current_version_id: null,
        files: [],
        links: [],
        versions: [],
        source_refs: []
      })
    );
    const versions = buildArtifactVersionsSurface({
      artifact_id: "artifact-001",
      current_version_id: null,
      versions: []
    });

    assert.equal(artifactDetailRoute("artifact 1"), "/api/v1/artifacts/artifact%201");
    assert.equal(
      artifactRenderJobRoute("artifact 1"),
      "/api/v1/artifacts/artifact%201/render-jobs"
    );
    assert.equal(artifactVersionsRoute("artifact 1"), "/api/v1/artifacts/artifact%201/versions");
    assert.equal(
      artifactFileMetadataRoute("file 1"),
      "/api/v1/artifact-files/file%201"
    );
    assert.equal(
      artifactFilePreviewRoute("file 1"),
      "/api/v1/artifact-files/file%201/preview"
    );
    assert.equal(
      artifactFileDownloadRoute("file 1"),
      "/api/v1/artifact-files/file%201/download"
    );
    assert.equal(draft.artifactStatus, "READY");
    assert.equal(draft.primaryFormat, "MD");
    assert.equal(draft.previewRoute, null);
    assert.deepEqual(draft.downloadRoutes, {});
    assert.equal(versions.versionCount, 0);
  });

  it("normalizes preview and download payloads without leaking server-only fields", () => {
    const preview = buildArtifactPreviewSurface(previewPayload());
    const download = buildArtifactDownloadSurface(downloadPayload());
    const serializedSummary = JSON.stringify(buildArtifactClientSummary(download));

    assert.equal(preview.previewSchemaVersion, AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION);
    assert.equal(preview.metadata.previewTextIncluded, true);
    assert.equal(download.downloadSchemaVersion, AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION);
    assert.equal(download.contentLength, download.content.length);
    assert.equal(serializedSummary.includes(download.content), false);
    assert.doesNotMatch(
      JSON.stringify({ preview, summary: buildArtifactClientSummary(download) }),
      /storage_ref|storage_path|service_token|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("reports HTTP, network, missing, invalid, and unsafe failures as typed errors", async () => {
    const httpClient = createFetchArtifactClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 404,
          payload: {
            error_code: "ae.artifact_not_found",
            detail: "missing",
            retryable: false
          }
        })
    });
    await assert.rejects(
      () => httpClient.getArtifact("missing"),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "ae.artifact_not_found" &&
        error.retryable === false
    );

    const networkClient = createFetchArtifactClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.getArtifact("artifact-001"),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    const mockClient = createMockArtifactClient({ artifacts: [artifactRecord()] });
    await assert.rejects(
      () => mockClient.getArtifact("missing"),
      error => error instanceof ArtifactClientError && error.status === "NOT_FOUND"
    );
    await assert.rejects(
      () => mockClient.getArtifactFile("missing-file"),
      error => error instanceof ArtifactClientError && error.status === "NOT_FOUND"
    );

    assert.throws(
      () => createFetchArtifactClient({ fetchImpl: "bad" }),
      error => error instanceof ArtifactClientError && error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => buildArtifactSurfaceFromRecord({ artifact_id: "" }),
      error => error instanceof ArtifactClientError && error.status === "ARTIFACT_FIELD_REQUIRED"
    );
    assert.throws(
      () => buildArtifactPreviewSurface({ preview_schema_version: "wrong" }),
      error => error instanceof ArtifactClientError && error.status === "ARTIFACT_PREVIEW_INVALID"
    );
    assert.throws(
      () => buildArtifactDownloadSurface({ download_schema_version: "wrong" }),
      error => error instanceof ArtifactClientError && error.status === "ARTIFACT_DOWNLOAD_INVALID"
    );
    assert.throws(
      () =>
        buildArtifactSurfaceFromRecord(
          artifactRecord({
            links: [
              {
                artifact_file_id: "artifact-file-001",
                link_type: "download",
                link_route: "https://external.example/download"
              }
            ]
          })
        ),
      error => error instanceof ArtifactClientError && error.status === "ARTIFACT_LINK_ROUTE_UNSAFE"
    );
    assert.throws(
      () =>
        buildArtifactSurfaceFromRecord(
          artifactRecord({
            display_title: "/data/nex-platform/private-file"
          })
        ),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "ARTIFACT_SURFACE_SENSITIVE_VALUE"
    );
    assert.deepEqual(findSensitiveArtifactClientKeys({ raw_prompt: "hidden" }), [
      "raw_prompt"
    ]);
  });

  it("builds safe export requests and summaries for multi-format render jobs", () => {
    const request = buildArtifactExportRequest({
      artifactId: "artifact-001",
      targetFormats: ["pdf", "MD", "PDF"]
    });
    const surface = buildArtifactExportSurface(
      {
        render_result_schema_version: "ae_markdown_render_result.v1",
        render_job: {
          render_job_id: "render-job-001",
          job_status: "COMPLETED",
          current_stage: "FINALIZING",
          progress_percent: 100
        },
        artifact: artifactRecord({
          current_version_id: "artifact-version-002",
          versions: [
            ...artifactRecord().versions,
            {
              artifact_version_id: "artifact-version-002",
              version_no: 2,
              source_content_hash: "c".repeat(64),
              artifact_content_hash: "d".repeat(64),
              rendered_formats: ["PDF", "MD"]
            }
          ],
          files: [
            ...artifactRecord().files,
            {
              artifact_file_id: "artifact-file-pdf-001",
              artifact_id: "artifact-001",
              artifact_version_id: "artifact-version-002",
              format: "PDF",
              mime_type: "application/pdf",
              file_name: "generated-report.pdf",
              storage_ref: "ae://artifacts/artifact-001/versions/artifact-version-002/generated-report.pdf",
              file_size_bytes: 4096,
              file_hash: "d".repeat(64),
              source_version_hash: "d".repeat(64)
            }
          ],
          links: [
            ...artifactRecord().links,
            {
              artifact_link_id: "artifact-link-pdf-download-001",
              artifact_file_id: "artifact-file-pdf-001",
              link_type: "download",
              access_policy: "owner_only",
              link_route: "/api/v1/artifact-files/artifact-file-pdf-001/download"
            }
          ]
        })
      },
      { requestedFormats: request.target_formats, route: request.route }
    );
    const summary = buildArtifactExportSummary(surface);

    assert.equal(
      request.artifact_export_request_schema_version,
      AE_WEB_ARTIFACT_EXPORT_REQUEST_SCHEMA_VERSION
    );
    assert.deepEqual(request.target_formats, ["PDF", "MD"]);
    assert.equal(request.route, "/api/v1/artifacts/artifact-001/render-jobs");
    assert.equal(
      surface.artifact_export_schema_version,
      AE_WEB_ARTIFACT_EXPORT_SURFACE_SCHEMA_VERSION
    );
    assert.equal(surface.renderJobId, "render-job-001");
    assert.deepEqual(surface.renderedFormats, ["PDF", "MD"]);
    assert.equal(summary.rendered_format_count, 2);
    assert.equal(JSON.stringify(surface).includes("storage_ref"), false);
    assert.doesNotMatch(JSON.stringify(summary), /\/data\/nex-platform|service_token/);
  });

  it("submits artifact export requests in mock and fetch modes", async () => {
    const mockClient = createMockArtifactClient({ artifacts: [artifactRecord()] });
    const mockResult = await mockClient.submitArtifactExportRequest({
      artifactId: "artifact-001",
      renderRequestId: "render-request-001",
      targetFormats: ["DOCX", "PDF"]
    });
    const refreshed = await mockClient.getArtifact("artifact-001");
    const versions = await mockClient.listArtifactVersions("artifact-001");

    assert.equal(mockResult.jobStatus, "COMPLETED");
    assert.deepEqual(mockResult.requestedFormats, ["DOCX", "PDF"]);
    assert.equal(refreshed.availableFormats.includes("PDF"), true);
    assert.equal(versions.versionCount, 2);

    const calls = [];
    const fetchClient = createFetchArtifactClient({
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({
          payload: {
            render_result_schema_version: "ae_markdown_render_result.v1",
            render_job: {
              render_job_id: "render-job-fetch-001",
              job_status: "COMPLETED",
              current_stage: "FINALIZING",
              progress_percent: 100
            },
            artifact: artifactRecord({
              current_version_id: "artifact-version-fetch-001",
              versions: [
                {
                  artifact_version_id: "artifact-version-fetch-001",
                  version_no: 1,
                  source_content_hash: "c".repeat(64),
                  artifact_content_hash: "e".repeat(64),
                  rendered_formats: ["HTML_PREVIEW"]
                }
              ]
            })
          }
        });
      }
    });
    const fetchResult = await fetchClient.submitArtifactExportRequest({
      artifactId: "artifact-001",
      renderRequestId: "render-request-fetch-001",
      targetFormats: ["HTML_PREVIEW"]
    });

    assert.equal(fetchResult.renderJobId, "render-job-fetch-001");
    assert.equal(calls[0].url, "/api/v1/artifacts/artifact-001/render-jobs");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers["Idempotency-Key"], "render-request-fetch-001");
    assert.deepEqual(JSON.parse(calls[0].options.body).target_formats, [
      "HTML_PREVIEW"
    ]);
  });

  it("rejects malformed export requests and responses", () => {
    assert.throws(
      () => buildArtifactExportRequest({ artifactId: "artifact-001", targetFormats: [] }),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "ARTIFACT_EXPORT_FORMATS_INVALID"
    );
    assert.throws(
      () => buildArtifactExportRequest({ artifactId: "artifact-001", targetFormats: ["TXT"] }),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "ARTIFACT_EXPORT_FORMAT_UNSUPPORTED"
    );
    assert.throws(
      () => buildArtifactExportSurface({ render_result_schema_version: "wrong" }),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "ARTIFACT_EXPORT_INVALID"
    );
    assert.throws(
      () => buildArtifactExportSummary({ artifact_export_schema_version: "wrong" }),
      error =>
        error instanceof ArtifactClientError &&
        error.status === "ARTIFACT_EXPORT_SUMMARY_INVALID"
    );
  });
});
