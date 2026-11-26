import { describe, expect, it } from "vitest";

import { projectBusinessJourney } from "./businessJourney";

describe("business journey projection", () => {
  it("admits ordered user-facing steps", () => {
    const result = projectBusinessJourney({
      schema_version: "eos_business_journey.v1",
      journey_kind: "BUSINESS_PROPOSAL",
      current_stage: "BUSINESS_APPROVAL",
      terminal: false,
      approval_stage_count: 2,
      steps: [
        { order: 1, code: "PROPOSAL_DRAFT", label: "품의서 작성", status: "COMPLETED" },
        { order: 2, code: "BUSINESS_APPROVAL", label: "품의 결재", status: "CURRENT" },
      ],
    });

    expect(result.approval_stage_count).toBe(2);
    expect(result.steps[1]).toMatchObject({ code: "BUSINESS_APPROVAL", status: "CURRENT" });
  });

  it.each([
    null,
    { schema_version: "legacy", steps: [] },
    { schema_version: "eos_business_journey.v1", journey_kind: "UNKNOWN", steps: [] },
    { schema_version: "eos_business_journey.v1", journey_kind: "ACCOUNTING_VOUCHER", current_stage: "X", terminal: false, approval_stage_count: null, steps: [{ order: 2, code: "X", label: "X", status: "CURRENT" }] },
    { schema_version: "eos_business_journey.v1", journey_kind: "ACCOUNTING_VOUCHER", current_stage: "X", terminal: false, approval_stage_count: null, steps: [{ order: 1, code: "X", label: "X", status: "INVALID" }] },
  ])("fails closed on malformed projection %#", value => {
    expect(() => projectBusinessJourney(value)).toThrow(TypeError);
  });
});
