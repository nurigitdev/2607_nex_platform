export const UX_ACCEPTANCE_V2_SCHEMA_VERSION = "ae_web_ux_acceptance.v2";

export const UX_ACCEPTANCE_V2_VIEWPORTS = Object.freeze({
  desktop: Object.freeze({ width: 1440, height: 900 }),
  mobile: Object.freeze({ width: 390, height: 844 }),
});

export const UX_ACCEPTANCE_V2_REGION_CATALOG = Object.freeze([
  "shell", "sidebar", "topbar", "main", "workspace", "context", "composer", "primary-result",
] as const);

export const UX_ACCEPTANCE_V2_REGION_PROFILES = Object.freeze({
  login: Object.freeze(["main"]),
  application: Object.freeze(["shell", "sidebar", "topbar", "main"]),
  workspace: Object.freeze(["shell", "sidebar", "topbar", "main", "workspace", "context", "composer"]),
  "workspace-result": Object.freeze(["shell", "sidebar", "topbar", "main", "workspace", "context", "composer", "primary-result"]),
});

export type UxAcceptanceProfile = keyof typeof UX_ACCEPTANCE_V2_REGION_PROFILES;
export type UxAcceptanceViewport = keyof typeof UX_ACCEPTANCE_V2_VIEWPORTS;

export interface UxAcceptanceV2Snapshot {
  readonly profile: UxAcceptanceProfile;
  readonly viewport: UxAcceptanceViewport;
  readonly language: string;
  readonly visibleMainCount: number;
  readonly visibleH1Count: number;
  readonly regionsPresent: readonly string[];
  readonly horizontalOverflow: boolean;
  readonly visibleControlCount: number;
  readonly unnamedControlCount: number;
  readonly smallTargetCount: number;
  readonly focusIndicatorMissingCount: number;
  readonly primaryRegionOverlapCount: number;
  readonly debugLeakageCount: number;
  readonly directServiceRequestCount: number;
  readonly protectedMaterialLeakageCount: number;
}

export interface UxAcceptanceV2Receipt {
  readonly schemaVersion: typeof UX_ACCEPTANCE_V2_SCHEMA_VERSION;
  readonly profile: UxAcceptanceProfile;
  readonly viewport: UxAcceptanceViewport;
  readonly status: "PASS" | "FAIL";
  readonly checks: Readonly<Record<string, boolean>>;
  readonly failedCheckIds: readonly string[];
  readonly observations: Readonly<{
    visibleControlCount: number;
    regionCount: number;
  }>;
}

export function evaluateUxAcceptanceV2(snapshot: UxAcceptanceV2Snapshot): UxAcceptanceV2Receipt {
  const requiredRegions = UX_ACCEPTANCE_V2_REGION_PROFILES[snapshot.profile];
  const present = new Set(snapshot.regionsPresent);
  const checks = Object.freeze({
    korean_document_language: normalizeLanguage(snapshot.language) === "ko",
    one_visible_main: snapshot.visibleMainCount === 1,
    one_visible_h1: snapshot.visibleH1Count === 1,
    required_regions_present: requiredRegions.every(region => present.has(region)),
    no_horizontal_overflow: snapshot.horizontalOverflow === false,
    all_visible_controls_named: snapshot.unnamedControlCount === 0,
    minimum_target_24px: snapshot.smallTargetCount === 0,
    focus_visible: snapshot.focusIndicatorMissingCount === 0,
    primary_regions_non_overlapping: snapshot.primaryRegionOverlapCount === 0,
    no_runtime_debug_leakage: snapshot.debugLeakageCount === 0,
    no_direct_service_request: snapshot.directServiceRequestCount === 0,
    no_protected_material_leakage: snapshot.protectedMaterialLeakageCount === 0,
  });
  const failedCheckIds = Object.entries(checks).filter(([, passed]) => !passed).map(([id]) => id);
  return Object.freeze({
    schemaVersion: UX_ACCEPTANCE_V2_SCHEMA_VERSION,
    profile: snapshot.profile,
    viewport: snapshot.viewport,
    status: failedCheckIds.length === 0 ? "PASS" : "FAIL",
    checks,
    failedCheckIds: Object.freeze(failedCheckIds),
    observations: Object.freeze({ visibleControlCount: snapshot.visibleControlCount, regionCount: present.size }),
  });
}

export function captureUxAcceptanceV2Snapshot({
  document,
  profile,
  viewport,
  requestUrls = [],
  primaryRegionOverlapCount = 0,
  focusIndicatorMissingCount = 0,
}: {
  readonly document: Document;
  readonly profile: UxAcceptanceProfile;
  readonly viewport: UxAcceptanceViewport;
  readonly requestUrls?: readonly string[];
  readonly primaryRegionOverlapCount?: number;
  readonly focusIndicatorMissingCount?: number;
}): UxAcceptanceV2Snapshot {
  const controls = Array.from(document.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [role='button']")).filter(isVisible);
  const text = document.body?.innerText ?? document.body?.textContent ?? "";
  const regionsPresent = Array.from(document.querySelectorAll<HTMLElement>("[data-ux-region]"))
    .map(element => element.dataset.uxRegion ?? "")
    .filter(Boolean);
  return Object.freeze({
    profile,
    viewport,
    language: document.documentElement.lang,
    visibleMainCount: Array.from(document.querySelectorAll<HTMLElement>("main")).filter(isVisible).length,
    visibleH1Count: Array.from(document.querySelectorAll<HTMLElement>("h1")).filter(isVisible).length,
    regionsPresent: Object.freeze([...new Set(regionsPresent)]),
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    visibleControlCount: controls.length,
    unnamedControlCount: controls.filter(control => !accessibleName(control, document)).length,
    smallTargetCount: controls.filter(isMeasurableSmallTarget).length,
    focusIndicatorMissingCount: nonNegativeInteger(focusIndicatorMissingCount),
    primaryRegionOverlapCount: nonNegativeInteger(primaryRegionOverlapCount),
    debugLeakageCount: countMatches(text, /(?:service_token|database_url|provider_endpoint|127\.0\.0\.1:81\d\d|\/data\/nex-platform)/gi),
    directServiceRequestCount: requestUrls.filter(value => isDirectServiceRequest(value, document.location.origin)).length,
    protectedMaterialLeakageCount: countMatches(text, /(?:bearer\s+[a-z0-9._-]+|nuri1004|ed6@c496em)/gi),
  });
}

function isVisible(element: HTMLElement) {
  if (element.hidden || element.getAttribute("aria-hidden") === "true") return false;
  const style = globalThis.getComputedStyle?.(element);
  return style?.display !== "none" && style?.visibility !== "hidden";
}

function accessibleName(element: HTMLElement, document: Document) {
  const direct = element.getAttribute("aria-label") || element.getAttribute("title") || element.textContent;
  if (direct?.trim()) return direct.trim();
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) return labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent ?? "").join(" ").trim();
  const id = element.id;
  return id ? document.querySelector<HTMLLabelElement>(`label[for="${cssEscape(id)}"]`)?.textContent?.trim() ?? "" : "";
}

function isMeasurableSmallTarget(element: HTMLElement) {
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && (rect.width < 24 || rect.height < 24);
}

function isDirectServiceRequest(value: string, origin: string) {
  try {
    const base = origin && origin !== "null" ? origin : "http://acceptance.local";
    const url = new URL(value, base);
    return /^81\d\d$/.test(url.port) || url.origin !== base || !url.pathname.startsWith("/ae-api/");
  } catch {
    return true;
  }
}

function countMatches(value: string, pattern: RegExp) {
  return [...value.matchAll(pattern)].length;
}

function nonNegativeInteger(value: number) {
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function normalizeLanguage(value: string) {
  return value.trim().toLowerCase().split("-")[0];
}

function cssEscape(value: string) {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/[^A-Za-z0-9_-]/g, "\\$&");
}
