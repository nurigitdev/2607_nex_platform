import { describe, expect, it } from "vitest";

import { validateCatalogParity } from "../locales/messages.js";
import {
  BUSINESS_TERMS,
  mapBusinessTerm,
  projectTechnicalStateDetail,
} from "./terminology";

describe("business terminology", () => {
  it("formalizes admitted Korean-default business language", () => {
    const expected = {
      WORKSPACE: "작업 공간",
      HUMAN_GATE: "승인",
      ARTIFACT: "결과물",
      READY_FOR_PROMPT: "입력 대기",
      DOCUMENT: "문서",
      ATTACHMENT: "첨부",
      SOURCE: "출처",
      RESULT: "업무 결과",
      PROJECT: "프로젝트",
    } as const;

    for (const term of BUSINESS_TERMS) {
      expect(mapBusinessTerm(term)).toMatchObject({
        term,
        known: true,
        label: expected[term],
      });
    }
    expect(validateCatalogParity().valid).toBe(true);
  });

  it("normalizes known terms but never echoes an unknown term", () => {
    expect(mapBusinessTerm("ready for prompt").term).toBe("READY_FOR_PROMPT");
    const unknown = mapBusinessTerm("PROVIDER_PRIVATE_TERM");
    expect(unknown).toMatchObject({
      term: "UNKNOWN",
      known: false,
      label: "업무 정보",
    });
    expect(JSON.stringify(unknown)).not.toContain("PROVIDER_PRIVATE_TERM");
  });

  it("exposes an original enum only through the explicit bounded debug path", () => {
    expect(projectTechnicalStateDetail("RESULT_VERIFY")).toBeNull();
    expect(projectTechnicalStateDetail("RESULT_VERIFY", { enabled: true })).toEqual({
      label: "기술 상태",
      value: "RESULT_VERIFY",
    });
    expect(projectTechnicalStateDetail("private/state", { enabled: true })).toBeNull();
    expect(projectTechnicalStateDetail("x".repeat(65), { enabled: true })).toBeNull();
  });
});
