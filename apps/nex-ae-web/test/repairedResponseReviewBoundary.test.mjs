import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_REPAIRED_RESPONSE_REVIEW_BOUNDARY_SCHEMA_VERSION,
  REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES,
  RepairedResponseReviewBoundaryError,
  buildRepairedResponseReviewBoundary,
  buildRepairedResponseReviewBoundarySummary,
  findSensitiveRepairedResponseReviewBoundaryKeys,
  validateRepairedResponseReviewBoundary
} from "../src/repairedResponseReviewBoundary.js";

describe("AE Web repaired response review boundary", () => {
  it("freezes chat interaction detail as the primary review surface", () => {
    const boundary = buildRepairedResponseReviewBoundary({
      reviewedAt: "2026-08-27T00:00:00Z"
    });
    const summary = buildRepairedResponseReviewBoundarySummary(boundary);

    assert.equal(
      boundary.boundary_schema_version,
      AE_WEB_REPAIRED_RESPONSE_REVIEW_BOUNDARY_SCHEMA_VERSION
    );
    assert.equal(boundary.primary_surface, "chat_interaction_detail");
    assert.deepEqual(boundary.secondary_surfaces, [
      "document_detail_link",
      "lineage_drilldown"
    ]);
    assert.equal(
      boundary.route_templates.collection,
      REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES.collection
    );
    assert.deepEqual(boundary.decision_controls.primary_actions, [
      "accept_repair",
      "keep_original"
    ]);
    assert.equal(summary.fetch_mode_supported, true);
    assert.equal(summary.primary_action_count, 2);
    assert.equal(summary.metadata.rawGenerationOutputRendered, false);
  });

  it("allows a narrower secondary surface set while keeping decision actions", () => {
    const boundary = buildRepairedResponseReviewBoundary({
      secondarySurfaces: ["document_detail_link"],
      secondaryActions: ["view_lineage"],
      clientModes: ["mock"]
    });

    assert.deepEqual(boundary.secondary_surfaces, ["document_detail_link"]);
    assert.deepEqual(boundary.decision_controls.secondary_actions, ["view_lineage"]);
    assert.deepEqual(boundary.client_modes, ["mock"]);
  });

  it("rejects unsupported surface, route, action, and storage mutations", () => {
    assert.throws(
      () => buildRepairedResponseReviewBoundary({ primarySurface: "document_detail" }),
      error =>
        error instanceof RepairedResponseReviewBoundaryError &&
        error.status === "PRIMARY_SURFACE_UNSUPPORTED"
    );
    assert.throws(
      () =>
        validateRepairedResponseReviewBoundary({
          ...buildRepairedResponseReviewBoundary(),
          route_templates: {
            ...REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES,
            detail: "/unsafe"
          }
        }),
      error =>
        error instanceof RepairedResponseReviewBoundaryError &&
        error.status === "ROUTE_TEMPLATE_INVALID"
    );
    assert.throws(
      () =>
        validateRepairedResponseReviewBoundary({
          ...buildRepairedResponseReviewBoundary(),
          decision_controls: {
            ...buildRepairedResponseReviewBoundary().decision_controls,
            primary_actions: ["accept_repair"]
          }
        }),
      error =>
        error instanceof RepairedResponseReviewBoundaryError &&
        error.status === "PRIMARY_ACTIONS_INCOMPLETE"
    );
    assert.throws(
      () =>
        validateRepairedResponseReviewBoundary({
          ...buildRepairedResponseReviewBoundary(),
          browser_storage_policy: {
            ...buildRepairedResponseReviewBoundary().browser_storage_policy,
            stores_raw_prompt: true
          }
        }),
      error =>
        error instanceof RepairedResponseReviewBoundaryError &&
        error.status === "BROWSER_STORAGE_POLICY_UNSAFE"
    );
  });

  it("keeps the boundary redaction-safe", () => {
    assert.deepEqual(
      findSensitiveRepairedResponseReviewBoundaryKeys({
        route_templates: { decision: REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES.decision },
        nested: [{ raw_prompt: "private" }, { service_token: "private" }]
      }),
      ["nested[0].raw_prompt", "nested[1].service_token"]
    );
    assert.throws(
      () =>
        validateRepairedResponseReviewBoundary({
          ...buildRepairedResponseReviewBoundary(),
          metadata: {
            ...buildRepairedResponseReviewBoundary().metadata,
            provider_url: "https://provider.local"
          }
        }),
      error =>
        error instanceof RepairedResponseReviewBoundaryError &&
        error.status === "BOUNDARY_SENSITIVE_KEY"
    );
  });
});
