export const DEFAULT_LOCALE = "ko";
export const SUPPORTED_LOCALES = Object.freeze(["ko", "en"]);

const ko = Object.freeze({
  "app.title": "NeX AE 작업 공간",
  "app.navigation": "주요 탐색",
  "app.workspace": "NeX-Platform 작업면",
  "nav.workspace": "워크스페이스",
  "nav.login": "로그인",
  "nav.runtime": "런타임",
  "nav.upload": "업로드",
  "nav.documents": "문서",
  "nav.detail": "상세",
  "nav.retrieval": "검색",
  "nav.artifact": "아티팩트",
  "nav.audit": "감사",
  "summary.label": "작업 현황",
  "summary.workspace": "워크스페이스",
  "summary.documents": "문서",
  "summary.progress": "진행",
  "summary.artifact": "아티팩트",
  "chat.region": "채팅과 진행 상태",
  "chat.eyebrow": "채팅 문서",
  "chat.title": "계약 기반 생성 흐름",
  "chat.prompt": "프롬프트",
  "chat.use_evidence": "근거 사용",
  "chat.output_format": "출력 형식",
  "action.send": "전송",
  "action.cancel": "취소",
  "action.inspect_recovery": "복구 확인",
  "action.retry": "재시도",
  "action.refresh": "새로고침",
  "action.apply": "적용",
  "generation.controls": "생성 작업 제어",
  "generation.none": "생성 작업 없음",
  "timeline.title": "진행 타임라인",
  "timeline.event_count": "{count}개 이벤트",
  "context.region": "컨텍스트 패널",
  "service.title": "서비스 상태",
  "auth.title": "사번 로그인",
  "auth.tenant": "테넌트",
  "auth.employee_id": "사번",
  "auth.password": "비밀번호",
  "auth.login": "로그인",
  "auth.logout": "로그아웃",
  "runtime.title": "런타임 진단",
  "upload.title": "업로드 준비",
  "upload.file": "파일",
  "upload.sha256": "SHA-256",
  "documents.title": "문서 범위",
  "document_detail.title": "문서 상세",
  "retrieval.title": "검색 범위",
  "artifact.title": "아티팩트",
  "artifact.filter": "아티팩트 목록 필터",
  "artifact.filter.all": "전체",
  "artifact.filter.ready": "준비됨",
  "artifact.filter.failed": "실패",
  "artifact.filter.downloadable": "다운로드 가능",
  "artifact.filter.previewable": "미리보기 가능",
  "audit.title": "AG 감사",
  "audit.redacted": "민감정보 제거됨",
  "status.completed": "완료",
  "status.skipped": "건너뜀",
  "status.running": "진행",
  "status.queued": "대기열",
  "status.ready": "준비",
  "status.already_exists": "이미 있음",
  "status.ready_for_handoff": "전달 준비",
  "status.ready_for_prompt": "입력 준비",
  "status.ready_for_submit": "전송 준비",
  "status.ready_for_rendering": "렌더링 준비",
  "status.ready_for_login": "로그인 준비",
  "status.preview_ready": "미리보기 준비",
  "status.download_ready": "다운로드 준비",
  "status.submitting": "전송 중",
  "status.authenticated": "인증됨",
  "status.failed": "실패",
  "status.logged_out": "로그아웃",
  "status.preview_only": "미리보기",
  "status.validated": "검증됨",
  "status.succeeded": "성공",
  "status.saved": "저장됨",
  "status.selected": "선택됨",
  "status.selecting": "선택 중",
  "status.export_ready": "내보내기 준비",
  "status.export_pending": "내보내기 진행",
  "status.empty": "비어 있음",
  "status.not_required": "불필요",
  "status.not_ready": "미준비",
  "status.unhealthy": "비정상",
  "status.unavailable": "사용 불가",
  "status.unknown": "알 수 없음",
  "status.high": "높음",
  "status.medium": "중간",
  "status.low": "낮음",
  "status.blocked": "차단됨",
  "status.cancelled": "취소됨",
  "status.cancelling": "취소 중",
  "status.recoverable": "복구 가능",
  "status.repair_required": "보완 필요"
});

const en = Object.freeze({
  "app.title": "NeX AE Workspace",
  "app.navigation": "Primary navigation",
  "app.workspace": "NeX-Platform Workspace",
  "nav.workspace": "Workspace",
  "nav.login": "Login",
  "nav.runtime": "Runtime",
  "nav.upload": "Upload",
  "nav.documents": "Documents",
  "nav.detail": "Details",
  "nav.retrieval": "Retrieval",
  "nav.artifact": "Artifacts",
  "nav.audit": "Audit",
  "summary.label": "Workspace status",
  "summary.workspace": "Workspace",
  "summary.documents": "Documents",
  "summary.progress": "Progress",
  "summary.artifact": "Artifact",
  "chat.region": "Chat and progress",
  "chat.eyebrow": "Chat document",
  "chat.title": "Contract-based generation flow",
  "chat.prompt": "Prompt",
  "chat.use_evidence": "Use evidence",
  "chat.output_format": "Output format",
  "action.send": "Send",
  "action.cancel": "Cancel",
  "action.inspect_recovery": "Check recovery",
  "action.retry": "Retry",
  "action.refresh": "Refresh",
  "action.apply": "Apply",
  "generation.controls": "Generation controls",
  "generation.none": "No generation job",
  "timeline.title": "Progress timeline",
  "timeline.event_count": "{count} events",
  "context.region": "Context panel",
  "service.title": "Service status",
  "auth.title": "Employee login",
  "auth.tenant": "Tenant",
  "auth.employee_id": "Employee ID",
  "auth.password": "Password",
  "auth.login": "Login",
  "auth.logout": "Logout",
  "runtime.title": "Runtime diagnostics",
  "upload.title": "Upload preparation",
  "upload.file": "File",
  "upload.sha256": "SHA-256",
  "documents.title": "Document scope",
  "document_detail.title": "Document details",
  "retrieval.title": "Retrieval scope",
  "artifact.title": "Artifact",
  "artifact.filter": "Artifact library filter",
  "artifact.filter.all": "All",
  "artifact.filter.ready": "Ready",
  "artifact.filter.failed": "Failed",
  "artifact.filter.downloadable": "Downloadable",
  "artifact.filter.previewable": "Previewable",
  "audit.title": "AG Audit",
  "audit.redacted": "Redacted",
  "status.completed": "Completed",
  "status.skipped": "Skipped",
  "status.running": "Running",
  "status.queued": "Queued",
  "status.ready": "Ready",
  "status.already_exists": "Already exists",
  "status.ready_for_handoff": "Ready for handoff",
  "status.ready_for_prompt": "Ready for prompt",
  "status.ready_for_submit": "Ready to submit",
  "status.ready_for_rendering": "Ready for rendering",
  "status.ready_for_login": "Ready for login",
  "status.preview_ready": "Preview ready",
  "status.download_ready": "Download ready",
  "status.submitting": "Submitting",
  "status.authenticated": "Authenticated",
  "status.failed": "Failed",
  "status.logged_out": "Logged out",
  "status.preview_only": "Preview only",
  "status.validated": "Validated",
  "status.succeeded": "Succeeded",
  "status.saved": "Saved",
  "status.selected": "Selected",
  "status.selecting": "Selecting",
  "status.export_ready": "Export ready",
  "status.export_pending": "Export pending",
  "status.empty": "Empty",
  "status.not_required": "Not required",
  "status.not_ready": "Not ready",
  "status.unhealthy": "Unhealthy",
  "status.unavailable": "Unavailable",
  "status.unknown": "Unknown",
  "status.high": "High",
  "status.medium": "Medium",
  "status.low": "Low",
  "status.blocked": "Blocked",
  "status.cancelled": "Cancelled",
  "status.cancelling": "Cancelling",
  "status.recoverable": "Recoverable",
  "status.repair_required": "Repair required"
});

export const MESSAGE_CATALOGS = Object.freeze({ ko, en });

export function normalizeLocale(locale) {
  const candidate = String(locale || "").trim().toLowerCase().split(/[-_]/)[0];
  return SUPPORTED_LOCALES.includes(candidate) ? candidate : DEFAULT_LOCALE;
}

export function validateCatalogParity(catalogs = MESSAGE_CATALOGS) {
  const baselineKeys = Object.keys(catalogs[DEFAULT_LOCALE] || {}).sort();
  const baseline = new Set(baselineKeys);
  const missingByLocale = {};
  const extraByLocale = {};

  for (const locale of SUPPORTED_LOCALES) {
    const localeKeys = Object.keys(catalogs[locale] || {}).sort();
    const localeSet = new Set(localeKeys);
    missingByLocale[locale] = baselineKeys.filter(key => !localeSet.has(key));
    extraByLocale[locale] = localeKeys.filter(key => !baseline.has(key));
  }

  return Object.freeze({
    valid: SUPPORTED_LOCALES.every(
      locale => missingByLocale[locale].length === 0 && extraByLocale[locale].length === 0
    ),
    keyCount: baselineKeys.length,
    missingByLocale: Object.freeze(missingByLocale),
    extraByLocale: Object.freeze(extraByLocale)
  });
}

export function message(key, { locale = DEFAULT_LOCALE, values = {} } = {}) {
  const resolvedLocale = normalizeLocale(locale);
  const template =
    MESSAGE_CATALOGS[resolvedLocale]?.[key] ??
    MESSAGE_CATALOGS[DEFAULT_LOCALE]?.[key] ??
    key;
  return String(template).replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
  );
}

export function statusMessage(status, locale = DEFAULT_LOCALE) {
  const rawStatus = String(status || "UNKNOWN").trim();
  const key = `status.${rawStatus.toLowerCase()}`;
  const translated = message(key, { locale });
  return translated === key ? rawStatus || "UNKNOWN" : translated;
}

export function applyDocumentMessages(root, locale = DEFAULT_LOCALE) {
  const resolvedLocale = normalizeLocale(locale);
  const documentElement = root?.documentElement;
  if (documentElement) {
    documentElement.lang = resolvedLocale;
    documentElement.dataset.locale = resolvedLocale;
  }

  applyAttribute(root, "[data-i18n]", "i18n", (node, value) => {
    node.textContent = value;
  }, resolvedLocale);
  applyAttribute(root, "[data-i18n-aria-label]", "i18nAriaLabel", (node, value) => {
    node.setAttribute("aria-label", value);
  }, resolvedLocale);
  applyAttribute(root, "[data-i18n-title]", "i18nTitle", (node, value) => {
    node.setAttribute("title", value);
  }, resolvedLocale);

  return Object.freeze({ locale: resolvedLocale, catalog: validateCatalogParity() });
}

function applyAttribute(root, selector, datasetKey, update, locale) {
  for (const node of root?.querySelectorAll?.(selector) || []) {
    const key = node.dataset?.[datasetKey];
    if (key) update(node, message(key, { locale }));
  }
}
