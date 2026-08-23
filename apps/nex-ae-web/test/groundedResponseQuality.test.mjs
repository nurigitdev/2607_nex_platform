import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_CHAT_GROUNDED_RESPONSE_QUALITY_SCHEMA_VERSION,
  AE_WEB_GROUNDED_RESPONSE_QUALITY_SURFACE_SCHEMA_VERSION,
  GroundedResponseQualitySurfaceError,
  buildGroundedResponseQualitySummary,
  buildGroundedResponseQualitySurface,
  extractGroundedResponseQuality
} from "../src/groundedResponseQuality.js";

function structuredQuality(overrides = {}) {
  return {
    contract_schema_version: "ae_chat_grounded_response_quality.v1",
    source_audit_schema_version:
      "cx_grounded_response_citation_quality_audit.v1",
    boundary_status: "PASS",
    citation_status: "VALIDATED",
    issue_count: 0,
    recommended_action: "proceed",
    grounding_required: true,
    retrieval_package_id: "cx-ret-001",
    retrieval_package_hash: "b".repeat(64),
    structured_draft_id: "draft-001",
    raw_output_included: false,
    evidence_text_included: false,
    prompt_text_included: false,
    provider_detail_included: false,
    ...overrides
  };
}

describe("AE Web grounded response quality surface", () => {
  it("maps structured AE chat quality contracts to safe visible UI state", () => {
    const surface = buildGroundedResponseQualitySurface({
      generation: {
        grounded_response_quality: structuredQuality({
          raw_output: "private generated output",
          evidence_text: "private evidence text"
        })
      }
    });
    const summary = buildGroundedResponseQualitySummary(surface);

    assert.equal(
      surface.quality_surface_schema_version,
      AE_WEB_GROUNDED_RESPONSE_QUALITY_SURFACE_SCHEMA_VERSION
    );
    assert.equal(
      surface.source_schema_version,
      AE_CHAT_GROUNDED_RESPONSE_QUALITY_SCHEMA_VERSION
    );
    assert.equal(surface.visible, true);
    assert.equal(surface.severity, "success");
    assert.equal(surface.boundary_status, "PASS");
    assert.equal(surface.citation_status, "VALIDATED");
    assert.equal(surface.retrieval_package_id_present, true);
    assert.equal(surface.retrieval_package_hash_present, true);
    assert.equal(surface.structured_draft_id_present, true);
    assert.equal(summary.metadata.rawOutputIncluded, false);
    assert.doesNotMatch(
      JSON.stringify(surface),
      /private generated output|private evidence text|raw_prompt|service_token|provider_url/
    );
  });

  it("normalizes warning, failure, and not-required statuses", () => {
    const warn = buildGroundedResponseQualitySurface(
      structuredQuality({
        boundary_status: "WARN",
        issue_count: 2,
        recommended_action: "proceed_with_caveat"
      })
    );
    const failed = buildGroundedResponseQualitySurface(
      structuredQuality({
        boundary_status: "FAIL",
        citation_status: "INVALID",
        recommended_action: "show_error"
      })
    );
    const notRequired = buildGroundedResponseQualitySurface(
      structuredQuality({
        source_audit_schema_version: null,
        boundary_status: "NOT_REQUIRED",
        citation_status: "NOT_REQUIRED",
        grounding_required: false,
        retrieval_package_id: null,
        retrieval_package_hash: null,
        structured_draft_id: null
      })
    );

    assert.equal(warn.visible, true);
    assert.equal(warn.severity, "warning");
    assert.equal(warn.issue_count, 2);
    assert.equal(failed.visible, true);
    assert.equal(failed.severity, "danger");
    assert.equal(failed.recommended_action, "show_error");
    assert.equal(notRequired.visible, false);
    assert.equal(notRequired.severity, "success");
  });

  it("builds fallback quality from legacy artifact quality summaries", () => {
    const extracted = extractGroundedResponseQuality({
      qualitySummary: {
        citationStatus: "VALIDATED",
        groundingRequired: true
      }
    });
    const surface = buildGroundedResponseQualitySurface({
      quality_summary: {
        citation_status: "PENDING",
        grounding_required: true
      }
    });

    assert.equal(extracted.boundary_status, "PASS");
    assert.equal(surface.boundary_status, "UNKNOWN");
    assert.equal(surface.citation_status, "UNKNOWN");
    assert.equal(surface.recommended_action, "proceed_with_caveat");
  });

  it("keeps sparse or invalid inputs safe and rejects invalid summaries", () => {
    const empty = buildGroundedResponseQualitySurface(null);
    const sparse = buildGroundedResponseQualitySurface({
      grounded_response_quality: {
        recommended_action: "unknown",
        boundary_status: "PRIVATE_STATUS",
        citation_status: "PRIVATE_CITATION",
        issue_count: -1,
        grounding_required: false,
        retrieval_package_id: " ",
        retrieval_package_hash: true,
        structured_draft_id: null,
        raw_output_included: true
      }
    });

    assert.equal(empty.recommended_action, "proceed");
    assert.equal(empty.visible, false);
    assert.equal(sparse.boundary_status, "NOT_REQUIRED");
    assert.equal(sparse.citation_status, "NOT_REQUIRED");
    assert.equal(sparse.issue_count, 0);
    assert.equal(sparse.retrieval_package_id_present, false);
    assert.equal(sparse.metadata.rawOutputIncluded, false);
    assert.throws(
      () => buildGroundedResponseQualitySummary({}),
      error =>
        error instanceof GroundedResponseQualitySurfaceError &&
        error.status === "GROUNDED_RESPONSE_QUALITY_SUMMARY_INVALID"
    );
  });
});
