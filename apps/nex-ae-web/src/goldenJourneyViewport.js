export const GOLDEN_JOURNEY_VIEWPORT_SCHEMA_VERSION =
  "ae_web_golden_journey_viewport.v1";

export const GOLDEN_JOURNEY_VIEWPORTS = Object.freeze({
  desktop: Object.freeze({ width: 1440, height: 900 }),
  mobile: Object.freeze({ width: 390, height: 844 })
});

export const GOLDEN_JOURNEY_REGION_SELECTORS = Object.freeze({
  sidebar: "#golden-sidebar",
  workspace: "#main-workspace",
  topbar: "#golden-topbar",
  summary: "#workspace-summary",
  content: "#golden-content",
  workspace_column: "#golden-workspace-column",
  context_pane: "#golden-context-pane",
  chat: "#golden-chat",
  timeline: "#golden-timeline"
});

export const GOLDEN_JOURNEY_NON_OVERLAP_PAIRS = Object.freeze([
  Object.freeze(["sidebar", "workspace"]),
  Object.freeze(["topbar", "summary"]),
  Object.freeze(["summary", "content"]),
  Object.freeze(["workspace_column", "context_pane"]),
  Object.freeze(["chat", "timeline"])
]);

const MIN_CONTROL_TARGET_PX = 24;

export function evaluateGoldenJourneyViewport(snapshot) {
  const expected = GOLDEN_JOURNEY_VIEWPORTS[snapshot?.viewportName];
  if (!expected) {
    throw new TypeError("golden journey viewport name is unsupported");
  }
  if (
    snapshot.viewportWidth !== expected.width ||
    snapshot.viewportHeight !== expected.height
  ) {
    throw new TypeError("golden journey viewport dimensions do not match contract");
  }
  const regions = Array.isArray(snapshot.regions) ? snapshot.regions : [];
  const controls = Array.isArray(snapshot.controls) ? snapshot.controls : [];
  const overlapPairs = Array.isArray(snapshot.overlapPairs)
    ? snapshot.overlapPairs
    : [];
  const requiredRegionNames = Object.keys(GOLDEN_JOURNEY_REGION_SELECTORS);
  const presentRegionNames = new Set(
    regions.filter(region => region?.present && region.width > 0 && region.height > 0)
      .map(region => region.name)
  );
  const unnamedControlCount = controls.filter(control => !control?.namePresent).length;
  const undersizedControlCount = controls.filter(
    control =>
      control?.visible &&
      (control.targetWidth < MIN_CONTROL_TARGET_PX ||
        control.targetHeight < MIN_CONTROL_TARGET_PX)
  ).length;
  const overlapCount = overlapPairs.filter(pair => pair?.overlapArea > 0).length;
  const checks = Object.freeze({
    korean_document: snapshot.htmlLang === "ko",
    single_main_landmark: snapshot.mainLandmarkCount === 1,
    single_primary_heading: snapshot.primaryHeadingCount === 1,
    required_regions_present: requiredRegionNames.every(name =>
      presentRegionNames.has(name)
    ),
    no_horizontal_overflow:
      Number.isFinite(snapshot.documentWidth) &&
      snapshot.documentWidth <= snapshot.viewportWidth + 1,
    controls_accessibly_named: controls.length > 0 && unnamedControlCount === 0,
    controls_meet_target_size: controls.length > 0 && undersizedControlCount === 0,
    focus_indicator_visible: snapshot.focusIndicatorVisible === true,
    primary_regions_do_not_overlap:
      overlapPairs.length === GOLDEN_JOURNEY_NON_OVERLAP_PAIRS.length &&
      overlapCount === 0
  });
  const issues = Object.entries(checks)
    .filter(([, passed]) => !passed)
    .map(([name]) => name.toUpperCase());
  return Object.freeze({
    viewport_evidence_schema_version: GOLDEN_JOURNEY_VIEWPORT_SCHEMA_VERSION,
    viewportName: snapshot.viewportName,
    status: issues.length === 0 ? "PASS" : "FAIL",
    checks,
    issues: Object.freeze(issues),
    summary: Object.freeze({
      viewportWidth: snapshot.viewportWidth,
      viewportHeight: snapshot.viewportHeight,
      documentWidth: snapshot.documentWidth,
      regionCount: presentRegionNames.size,
      controlCount: controls.length,
      unnamedControlCount,
      undersizedControlCount,
      overlapCount
    })
  });
}

export function rectangleOverlapArea(first, second) {
  if (!first || !second) return 0;
  const width = Math.max(
    0,
    Math.min(first.x + first.width, second.x + second.width) -
      Math.max(first.x, second.x)
  );
  const height = Math.max(
    0,
    Math.min(first.y + first.height, second.y + second.height) -
      Math.max(first.y, second.y)
  );
  return width * height;
}
