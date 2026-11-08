import { describe, expect, it } from "vitest";

import { validateCatalogParity } from "../locales/messages.js";
import {
  WORK_STATES,
  isWorkState,
  mapApprovalState,
  mapWorkState,
} from "./workState";

describe("user-facing work state mapper", () => {
  it("maps every canonical state to one stable presentation", () => {
    const expected = {
      requested: ["요청됨", "neutral", "request", false, "review_request"],
      in_progress: ["처리 중", "info", "progress", false, "view_progress"],
      waiting_approval: ["승인 대기", "warning", "approval", false, "review_approval"],
      completed: ["완료", "success", "success", true, "view_result"],
      failed: ["처리 실패", "danger", "error", true, "retry"],
      cancelled: ["취소됨", "neutral", "cancelled", true, null],
    } as const;

    expect(WORK_STATES).toHaveLength(6);
    expect(Object.isFrozen(WORK_STATES)).toBe(true);
    for (const state of WORK_STATES) {
      const presentation = mapWorkState(state);
      expect([
        presentation.label,
        presentation.tone,
        presentation.iconRole,
        presentation.terminal,
        presentation.defaultAction?.kind ?? null,
      ]).toEqual(expected[state]);
      expect(presentation.known).toBe(true);
      expect(presentation.ariaLabel).toBe(presentation.label);
      expect(presentation.technicalDetailRef).toBeNull();
    }
  });

  it("normalizes case and surrounding whitespace without creating aliases", () => {
    expect(mapWorkState("  WAITING_APPROVAL  ")).toEqual(mapWorkState("waiting_approval"));
    expect(isWorkState("completed")).toBe(true);
    expect(isWorkState("COMPLETED")).toBe(false);
    expect(isWorkState("pending")).toBe(false);
  });

  it("fails closed for unknown states without disclosing the input", () => {
    const secretState = "PROVIDER_X_RUNTIME_JOB_8675309";
    const presentation = mapWorkState(secretState);

    expect(presentation).toMatchObject({
      state: "unknown",
      known: false,
      label: "상태 확인 필요",
      tone: "neutral",
      iconRole: "unknown",
      terminal: null,
      defaultAction: null,
      technicalDetailRef: "UX_STATE_UNRECOGNIZED",
    });
    expect(JSON.stringify(presentation)).not.toContain(secretState);
    expect(mapWorkState(null)).toEqual(presentation);
  });

  it("keeps terminal semantics and permitted default action presentation explicit", () => {
    expect(WORK_STATES.filter(state => mapWorkState(state).terminal)).toEqual([
      "completed",
      "failed",
      "cancelled",
    ]);
    expect(mapWorkState("failed").defaultAction).toMatchObject({
      kind: "retry",
      label: "재시도",
    });
    expect(mapWorkState("cancelled").defaultAction).toBeNull();
  });

  it("pairs tone with a semantic icon role and visible accessible label", () => {
    const requested = mapWorkState("requested");
    const cancelled = mapWorkState("cancelled");

    expect(requested.tone).toBe(cancelled.tone);
    expect(requested.iconRole).not.toBe(cancelled.iconRole);
    for (const state of WORK_STATES) {
      const presentation = mapWorkState(state);
      expect(presentation.label).not.toBe("");
      expect(presentation.ariaLabel).toBe(presentation.label);
      expect(presentation.iconRole).not.toBe("");
    }
  });

  it("keeps Korean and English state and action message keys in parity", () => {
    const parity = validateCatalogParity();
    const ko = mapWorkState("waiting_approval", "ko-KR");
    const en = mapWorkState("waiting_approval", "en-US");

    expect(parity.valid).toBe(true);
    expect(ko.labelKey).toBe(en.labelKey);
    expect(ko.defaultAction?.labelKey).toBe(en.defaultAction?.labelKey);
    expect(ko.label).toBe("승인 대기");
    expect(en.label).toBe("Waiting for approval");
    expect(ko.defaultAction?.label).toBe("승인 검토");
    expect(en.defaultAction?.label).toBe("Review approval");
  });

  it("projects approval outcomes without confusing rejection with work failure", () => {
    const pending = mapApprovalState("PENDING");
    const rejected = mapApprovalState("rejected");

    expect(pending).toMatchObject({
      outcome: "pending",
      label: "승인 대기",
      tone: "warning",
      terminal: false,
      work: { state: "waiting_approval" },
    });
    expect(rejected).toMatchObject({
      outcome: "rejected",
      label: "반려됨",
      tone: "danger",
      terminal: true,
      work: { state: "completed" },
    });
  });

  it("fails closed for an unknown approval outcome without echoing it", () => {
    const raw = "PROVIDER_APPROVAL_123";
    const presentation = mapApprovalState(raw, "en");

    expect(presentation).toMatchObject({
      outcome: "unknown",
      label: "Status needs review",
      terminal: null,
      work: { technicalDetailRef: "UX_STATE_UNRECOGNIZED" },
    });
    expect(JSON.stringify(presentation)).not.toContain(raw);
  });
});
