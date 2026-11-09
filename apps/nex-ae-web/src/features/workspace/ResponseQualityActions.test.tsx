import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildRepairedResponseReviewSurfaceFromProjection } from "../../repairedResponseReviewClient.js";
import { createRepairedResponseDecisionState } from "../../repairedResponseDecisionState.js";
import { ResponseQualityActions } from "./ResponseQualityActions";

const buildReviewSurface = buildRepairedResponseReviewSurfaceFromProjection as unknown as (
  projection: Readonly<Record<string, unknown>>,
) => any;

describe("ResponseQualityActions", () => {
  it("submits accessible generation feedback values", async () => {
    const user = userEvent.setup();
    const onFeedback = vi.fn();
    render(
      <ResponseQualityActions
        feedback={{ status: "READY", value: null }}
        onFeedback={onFeedback}
      />,
    );

    await user.click(screen.getByRole("button", { name: "도움됨" }));
    expect(onFeedback).toHaveBeenCalledWith("positive");
    expect(screen.getByRole("button", { name: "도움됨" })).toHaveAttribute(
      "data-generation-feedback-value",
      "positive",
    );
  });

  it("renders only the admitted repaired preview and records a decision", async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn();
    const surface = buildReviewSurface(reviewProjection());
    surface.decisionState = createRepairedResponseDecisionState({ clientMode: "fetch" });
    render(
      <ResponseQualityActions
        repairedResponseReview={surface}
        onRepairedDecision={onDecision}
      />,
    );

    expect(screen.getByRole("heading", { name: "수정된 응답 검토" })).toBeInTheDocument();
    expect(screen.getByText("근거 누락 지점을 보강했습니다.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/raw_prompt|service_token|storage_path/i);
    await user.click(screen.getByRole("button", { name: "수정본 적용" }));
    expect(onDecision).toHaveBeenCalledWith("accept_repair");
    expect(screen.getByRole("button", { name: "수정본 적용" })).toHaveAttribute(
      "data-repaired-response-decision-action",
      "accept_repair",
    );
  });

  it("fails closed for an invalid repaired-response projection", () => {
    const { container } = render(<ResponseQualityActions repairedResponseReview={{ raw_prompt: "private" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

function reviewProjection() {
  return {
    projection_schema_version: "ae_repaired_response_review_projection.v1",
    projection_status: "READY_FOR_DECISION",
    repaired_response_handoff_id: "handoff-001",
    handoff_request_id: "request-001",
    owner_scope: { tenant_id: "VO00", workspace_id: "workspace-1", owner_user_id: "employee-1" },
    conversation_scope: { chat_document_id: "conversation-1", interaction_id: "interaction-1" },
    review_card: { title: "수정 응답 검토", presentation_mode: "side_by_side_review", default_action: "review_repair" },
    original_response_ref: { cx_generation_id: "generation-original", link: "/api/v1/generations/generation-original", parent_generation_mutated: false },
    repaired_response_summary: {
      cx_generation_id: "generation-repaired",
      status: "SUCCEEDED",
      alias: "default",
      provider_capability: "grounded_generation",
      finish_reason: "stop",
      output_hash: "a".repeat(64),
      output_preview: "근거 누락 지점을 보강했습니다.",
      usage: { input_tokens: 10, output_tokens: 12, total_tokens: 22 },
      quality_summary: { grounding_required: true, retrieval_package_id: "retrieval-1", grounded_response_quality_status: "PASS" },
    },
    lineage_summary: {
      remediation_action_id: "remediation-1",
      lineage_status: "REPAIRED",
      action_type: "regenerate_answer",
      lineage_type: "repair",
      attempt_no: 2,
      result_ref: { kind: "cx_generation", id: "generation-repaired" },
    },
    decision_controls: {
      available_actions: ["view_original", "view_repaired", "accept_repair", "keep_original", "view_lineage"],
      primary_actions: ["accept_repair", "keep_original"],
      secondary_actions: ["view_original", "view_repaired", "view_lineage"],
      decision_submit_path: "/api/v1/chat/interactions/interaction-1/repaired-response-handoffs/handoff-001/decisions",
      idempotency_key_hint: "request-001",
    },
    links: {
      handoff: "/api/v1/chat/interactions/interaction-1/repaired-response-handoffs/handoff-001",
      original_generation: "/api/v1/generations/generation-original",
      repaired_generation: "/api/v1/generations/generation-repaired",
      remediation_execution: "/api/v1/generations/generation-original/remediation-executions/remediation-1",
    },
    redaction_summary: {
      raw_output_included: false,
      raw_prompt_included: false,
      raw_source_text_included: false,
      evidence_text_included: false,
      provider_detail_included: false,
      storage_path_included: false,
    },
    checked_at: "2026-11-09T00:00:00Z",
  };
}
