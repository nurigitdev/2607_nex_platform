import { describe, expect, it } from "vitest";

import {
  UX_ACCEPTANCE_V2_REGION_CATALOG,
  UX_ACCEPTANCE_V2_SCHEMA_VERSION,
  UX_ACCEPTANCE_V2_VIEWPORTS,
  captureUxAcceptanceV2Snapshot,
  evaluateUxAcceptanceV2,
  type UxAcceptanceV2Snapshot,
} from "./uxAcceptanceV2";

describe("UX acceptance v2 contract", () => {
  it("freezes schema, required viewports, and complete region catalog", () => {
    expect(UX_ACCEPTANCE_V2_SCHEMA_VERSION).toBe("ae_web_ux_acceptance.v2");
    expect(UX_ACCEPTANCE_V2_VIEWPORTS).toEqual({ desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } });
    expect(UX_ACCEPTANCE_V2_REGION_CATALOG).toEqual(["shell", "sidebar", "topbar", "main", "workspace", "context", "composer", "primary-result"]);
  });

  it("passes a complete Korean workspace result snapshot", () => {
    const receipt = evaluateUxAcceptanceV2(validSnapshot());
    expect(receipt.status).toBe("PASS");
    expect(receipt.failedCheckIds).toEqual([]);
    expect(receipt.checks).toEqual(expect.objectContaining({
      korean_document_language: true,
      required_regions_present: true,
      no_direct_service_request: true,
    }));
  });

  it("fails closed with stable check ids for every invariant family", () => {
    const receipt = evaluateUxAcceptanceV2({
      ...validSnapshot(),
      language: "en",
      visibleMainCount: 2,
      visibleH1Count: 0,
      regionsPresent: ["main"],
      horizontalOverflow: true,
      unnamedControlCount: 1,
      smallTargetCount: 1,
      focusIndicatorMissingCount: 1,
      primaryRegionOverlapCount: 1,
      debugLeakageCount: 1,
      directServiceRequestCount: 1,
      protectedMaterialLeakageCount: 1,
    });
    expect(receipt.status).toBe("FAIL");
    expect(receipt.failedCheckIds).toHaveLength(12);
    expect(receipt.failedCheckIds).toContain("minimum_target_24px");
    expect(receipt.failedCheckIds).toContain("no_protected_material_leakage");
  });

  it("captures named controls, stable regions, and same-origin request boundaries", () => {
    document.documentElement.lang = "ko-KR";
    document.body.innerHTML = `
      <div data-ux-region="shell">
        <aside data-ux-region="sidebar"></aside>
        <header data-ux-region="topbar"></header>
        <main data-ux-region="main">
          <section data-ux-region="workspace"><h1>작업 공간</h1>
            <form data-ux-region="composer"><label for="prompt">업무 요청</label><textarea id="prompt"></textarea><button>보내기</button></form>
            <aside data-ux-region="context"></aside>
          </section>
        </main>
      </div>`;
    const snapshot = captureUxAcceptanceV2Snapshot({
      document,
      profile: "workspace",
      viewport: "desktop",
      requestUrls: ["/ae-api/api/v1/workspaces"],
    });
    expect(snapshot.unnamedControlCount).toBe(0);
    expect(snapshot.directServiceRequestCount).toBe(0);
    expect(evaluateUxAcceptanceV2(snapshot).status).toBe("PASS");
  });

  it("detects unnamed controls, debug leakage, protected material, and direct ports", () => {
    document.documentElement.lang = "ko";
    document.body.innerHTML = `<main data-ux-region="main"><h1>진단</h1><button aria-label=""></button><p>database_url=hidden Bearer abc.def.ghi</p></main>`;
    const snapshot = captureUxAcceptanceV2Snapshot({
      document,
      profile: "login",
      viewport: "mobile",
      requestUrls: ["http://127.0.0.1:8102/health", "https://outside.example/ae-api/health"],
    });
    expect(snapshot.unnamedControlCount).toBe(1);
    expect(snapshot.debugLeakageCount).toBeGreaterThan(0);
    expect(snapshot.protectedMaterialLeakageCount).toBeGreaterThan(0);
    expect(snapshot.directServiceRequestCount).toBe(2);
    expect(evaluateUxAcceptanceV2(snapshot).status).toBe("FAIL");
  });

  it("uses a wrapping label and its activation area for choice controls", () => {
    document.documentElement.lang = "ko";
    document.body.innerHTML = `
      <main data-ux-region="main">
        <h1>작업 공간</h1>
        <label style="display:flex;width:80px;height:32px">
          <input type="checkbox" style="width:16px;height:16px" />
          <span>근거 사용</span>
        </label>
      </main>`;
    const receipt = evaluateUxAcceptanceV2(captureUxAcceptanceV2Snapshot({
      document,
      profile: "login",
      viewport: "desktop",
    }));
    expect(receipt.checks.all_visible_controls_named).toBe(true);
    expect(receipt.checks.minimum_target_24px).toBe(true);
  });

  it("does not measure a clipped native file input as the visible activation target", () => {
    document.documentElement.lang = "ko";
    document.body.innerHTML = `
      <main data-ux-region="main">
        <h1>작업 공간</h1>
        <input aria-label="파일 선택" type="file" style="position:absolute;width:1px;height:1px;clip-path:inset(50%)" />
        <button style="width:32px;height:32px">파일 첨부</button>
      </main>`;
    const receipt = evaluateUxAcceptanceV2(captureUxAcceptanceV2Snapshot({
      document,
      profile: "login",
      viewport: "desktop",
    }));
    expect(receipt.checks.minimum_target_24px).toBe(true);
  });
});

function validSnapshot(): UxAcceptanceV2Snapshot {
  return {
    profile: "workspace-result",
    viewport: "desktop",
    language: "ko-KR",
    visibleMainCount: 1,
    visibleH1Count: 1,
    regionsPresent: ["shell", "sidebar", "topbar", "main", "workspace", "context", "composer", "primary-result"],
    horizontalOverflow: false,
    visibleControlCount: 8,
    unnamedControlCount: 0,
    smallTargetCount: 0,
    focusIndicatorMissingCount: 0,
    primaryRegionOverlapCount: 0,
    debugLeakageCount: 0,
    directServiceRequestCount: 0,
    protectedMaterialLeakageCount: 0,
  };
}
