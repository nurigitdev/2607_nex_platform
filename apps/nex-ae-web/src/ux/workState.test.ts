import { describe, expect, it } from "vitest";

import { validateCatalogParity } from "../locales/messages.js";
import {
  WORK_STATES,
  WORK_STATE_SOURCES,
  isWorkState,
  mapApprovalState,
  mapSourceWorkState,
  mapWorkState,
} from "./workState";

describe("user-facing work state mapper", () => {
  it("maps every canonical state to one stable presentation", () => {
    const expected = {
      IDLE: ["입력 대기", "neutral", "request", false, null],
      ACCEPTING: ["요청 접수", "neutral", "request", false, "review_request"],
      PLANNING: ["업무 계획", "info", "progress", false, "view_progress"],
      RUNNING: ["처리 중", "info", "progress", false, "view_progress"],
      WAITING_APPROVAL: ["승인 대기", "warning", "approval", false, "review_approval"],
      RESUMING: ["처리 재개", "info", "progress", false, "view_progress"],
      VERIFYING: ["결과 확인", "info", "progress", false, "view_progress"],
      SUCCEEDED: ["완료", "success", "success", true, "view_result"],
      PARTIAL: ["일부 완료", "warning", "warning", true, "view_result"],
      FAILED: ["처리 실패", "danger", "error", true, "retry"],
      CANCELLED: ["취소됨", "neutral", "cancelled", true, null],
    } as const;

    expect(WORK_STATES).toHaveLength(11);
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
      expect(presentation).toMatchObject({ known: true, state });
      expect(presentation.ariaLabel).toBe(presentation.label);
      expect(presentation.technicalDetailRef).toBeNull();
    }
  });

  it("keeps compatibility inputs while making uppercase values canonical", () => {
    expect(mapWorkState("  waiting approval  ")).toEqual(mapWorkState("WAITING_APPROVAL"));
    expect(mapWorkState("requested").state).toBe("ACCEPTING");
    expect(mapWorkState("in_progress").state).toBe("RUNNING");
    expect(mapWorkState("completed").state).toBe("SUCCEEDED");
    expect(isWorkState("SUCCEEDED")).toBe(true);
    expect(isWorkState("succeeded")).toBe(false);
  });

  it("maps each admitted source without inventing progress", () => {
    expect(WORK_STATE_SOURCES).toHaveLength(6);
    expect(mapSourceWorkState("AgentExecution", "COMPILED").state).toBe("PLANNING");
    expect(mapSourceWorkState("GenerationLifecycle", "ACTIVE").state).toBe("RUNNING");
    expect(mapSourceWorkState("Approval", "PENDING").state).toBe("WAITING_APPROVAL");
    expect(mapSourceWorkState("ResultDelivery", "ACKNOWLEDGED").state).toBe("SUCCEEDED");
    expect(mapSourceWorkState("Artifact", "PARTIAL").state).toBe("PARTIAL");
    expect(mapSourceWorkState("OperationState", "failed").state).toBe("FAILED");

    expect(mapSourceWorkState("AgentExecution", "UNKNOWN_ACTIVE_STATE")).toMatchObject({
      state: "UNKNOWN",
      known: false,
      terminal: null,
    });
    expect(mapSourceWorkState("UnknownSource", "RUNNING").state).toBe("UNKNOWN");
  });

  it("fails closed for unknown states without disclosing the input", () => {
    const secretState = "PROVIDER_X_RUNTIME_JOB_8675309";
    const presentation = mapWorkState(secretState);

    expect(presentation).toMatchObject({
      state: "UNKNOWN",
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

  it("keeps partial, failure, cancellation, and approval semantics distinct", () => {
    expect(mapWorkState("PARTIAL")).toMatchObject({ terminal: true, tone: "warning" });
    expect(mapWorkState("FAILED")).toMatchObject({ terminal: true, tone: "danger" });
    expect(mapWorkState("CANCELLED")).toMatchObject({ terminal: true, tone: "neutral" });
    expect(mapWorkState("WAITING_APPROVAL")).toMatchObject({
      terminal: false,
      tone: "warning",
    });
  });

  it("keeps Korean and English state and action keys in parity", () => {
    const parity = validateCatalogParity();
    const ko = mapWorkState("WAITING_APPROVAL", "ko-KR");
    const en = mapWorkState("WAITING_APPROVAL", "en-US");

    expect(parity.valid).toBe(true);
    expect(ko.labelKey).toBe(en.labelKey);
    expect(ko.defaultAction?.labelKey).toBe(en.defaultAction?.labelKey);
    expect(ko.label).toBe("승인 대기");
    expect(en.label).toBe("Waiting for approval");
  });

  it("projects approval outcomes without confusing rejection with work failure", () => {
    const pending = mapApprovalState("PENDING");
    const rejected = mapApprovalState("rejected");

    expect(pending).toMatchObject({
      outcome: "pending",
      label: "승인 대기",
      tone: "warning",
      terminal: false,
      work: { state: "WAITING_APPROVAL" },
    });
    expect(rejected).toMatchObject({
      outcome: "rejected",
      label: "반려됨",
      tone: "danger",
      terminal: true,
      work: { state: "SUCCEEDED" },
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
