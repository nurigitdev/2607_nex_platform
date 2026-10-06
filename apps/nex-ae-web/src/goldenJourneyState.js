export const GOLDEN_JOURNEY_SCHEMA_VERSION = "ae_web_golden_journey.v1";
export const GOLDEN_JOURNEY_EVIDENCE_SCHEMA_VERSION =
  "ae_web_golden_journey_evidence.v1";

export const GOLDEN_JOURNEY_STAGES = Object.freeze([
  "SESSION_AUTHENTICATED",
  "UPLOAD_ACCEPTED",
  "INGESTION_INDEXED",
  "RETRIEVAL_READY",
  "GENERATION_COMPLETED",
  "GROUNDING_ACCEPTED",
  "ARTIFACT_READY",
  "PREVIEW_READY",
  "DOWNLOAD_READY"
]);

const SAFE_REF_KEYS = new Set([
  "subject_ref",
  "tenant_ref",
  "workspace_id",
  "upload_handoff_id",
  "document_id",
  "source_file_id",
  "processing_run_id",
  "interaction_id",
  "retrieval_id",
  "generation_id",
  "response_id",
  "artifact_id",
  "artifact_file_id"
]);

const SAFE_DETAIL_KEYS = new Set([
  "warning_count",
  "citation_count",
  "repair_attempt_count",
  "quality_status",
  "download_format",
  "viewport_name",
  "viewport_width",
  "viewport_height"
]);

const SAFE_DETAIL_VALUES = Object.freeze({
  quality_status: new Set(["VALIDATED", "REPAIRED"]),
  download_format: new Set(["MD", "HTML_PREVIEW", "PDF"]),
  viewport_name: new Set(["desktop", "mobile"])
});

const SAFE_CODE = /^[A-Z][A-Z0-9_]{0,63}$/;
const SAFE_OPAQUE_REF = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export function createGoldenJourneyState({ journeyId, startedAt, locale = "ko" }) {
  assertOpaqueRef("journey_id", journeyId);
  const normalizedStartedAt = requireTimestamp(startedAt, "started_at");
  const normalizedLocale = String(locale || "").trim().toLowerCase();
  if (!["ko", "en"].includes(normalizedLocale)) {
    throw new TypeError("golden journey locale is unsupported");
  }
  return freezeState({
    journey_schema_version: GOLDEN_JOURNEY_SCHEMA_VERSION,
    journey_id: journeyId,
    locale: normalizedLocale,
    status: "READY",
    current_stage: null,
    completed_stages: [],
    events: [],
    started_at: normalizedStartedAt,
    updated_at: normalizedStartedAt,
    failure: null
  });
}

export function advanceGoldenJourney(
  state,
  { stage, occurredAt, refs = {}, details = {} }
) {
  assertGoldenJourneyState(state);
  if (state.status === "FAILED" || state.status === "COMPLETED") {
    throw new TypeError("golden journey is terminal");
  }
  const expectedStage = GOLDEN_JOURNEY_STAGES[state.completed_stages.length];
  if (stage !== expectedStage) {
    throw new TypeError(`golden journey expected ${expectedStage || "no stage"}`);
  }
  const timestamp = requireTimestamp(occurredAt, "occurred_at");
  assertMonotonicTimestamp(state.updated_at, timestamp);
  const safeRefs = normalizeSafeRefs(refs);
  const safeDetails = normalizeSafeDetails(details);
  const completedStages = [...state.completed_stages, stage];
  const completed = completedStages.length === GOLDEN_JOURNEY_STAGES.length;
  return freezeState({
    ...state,
    status: completed ? "COMPLETED" : "RUNNING",
    current_stage: stage,
    completed_stages: completedStages,
    events: [
      ...state.events,
      Object.freeze({
        stage,
        status: "COMPLETED",
        occurred_at: timestamp,
        refs: safeRefs,
        details: safeDetails
      })
    ],
    updated_at: timestamp
  });
}

export function failGoldenJourney(
  state,
  { failureCode, occurredAt, retryable = false }
) {
  assertGoldenJourneyState(state);
  if (state.status === "FAILED" || state.status === "COMPLETED") {
    throw new TypeError("golden journey is terminal");
  }
  if (!SAFE_CODE.test(String(failureCode || ""))) {
    throw new TypeError("golden journey failure code is invalid");
  }
  const timestamp = requireTimestamp(occurredAt, "occurred_at");
  assertMonotonicTimestamp(state.updated_at, timestamp);
  if (typeof retryable !== "boolean") {
    throw new TypeError("golden journey retryable flag must be boolean");
  }
  return freezeState({
    ...state,
    status: "FAILED",
    updated_at: timestamp,
    failure: Object.freeze({
      failure_code: failureCode,
      failed_stage:
        GOLDEN_JOURNEY_STAGES[state.completed_stages.length] || "JOURNEY_COMPLETED",
      retryable,
      occurred_at: timestamp
    })
  });
}

export function buildGoldenJourneyEvidence(state) {
  assertGoldenJourneyState(state);
  const evidence = {
    evidence_schema_version: GOLDEN_JOURNEY_EVIDENCE_SCHEMA_VERSION,
    journey_id: state.journey_id,
    locale: state.locale,
    status: state.status,
    current_stage: state.current_stage,
    completed_stage_count: state.completed_stages.length,
    expected_stage_count: GOLDEN_JOURNEY_STAGES.length,
    stages: state.events.map(event => ({
      stage: event.stage,
      status: event.status,
      occurred_at: event.occurred_at,
      refs: { ...event.refs },
      details: { ...event.details }
    })),
    started_at: state.started_at,
    updated_at: state.updated_at,
    failure: state.failure ? { ...state.failure } : null,
    redaction: {
      private_payload_included: false,
      credential_material_included: false,
      provider_or_database_location_included: false
    }
  };
  assertBrowserSafeEvidence(evidence);
  return evidence;
}

export function assertBrowserSafeEvidence(evidence) {
  if (!evidence || evidence.evidence_schema_version !== GOLDEN_JOURNEY_EVIDENCE_SCHEMA_VERSION) {
    throw new TypeError("golden journey evidence schema is invalid");
  }
  const serialized = JSON.stringify(evidence);
  if (
    /password|token|raw_prompt|document_text|generated_text|source_bytes|storage_ref|provider_url|database_url|\/data\//i.test(
      serialized
    )
  ) {
    throw new TypeError("golden journey evidence contains private material");
  }
  return evidence;
}

function assertGoldenJourneyState(state) {
  if (!state || state.journey_schema_version !== GOLDEN_JOURNEY_SCHEMA_VERSION) {
    throw new TypeError("golden journey state schema is invalid");
  }
  if (!Array.isArray(state.completed_stages) || !Array.isArray(state.events)) {
    throw new TypeError("golden journey state collections are invalid");
  }
}

function normalizeSafeRefs(refs) {
  if (!refs || typeof refs !== "object" || Array.isArray(refs)) {
    throw new TypeError("golden journey refs must be an object");
  }
  const normalized = {};
  for (const [key, value] of Object.entries(refs)) {
    if (!SAFE_REF_KEYS.has(key)) {
      throw new TypeError(`golden journey ref key is not allowed: ${key}`);
    }
    assertOpaqueRef(key, value);
    normalized[key] = value;
  }
  return Object.freeze(normalized);
}

function normalizeSafeDetails(details) {
  if (!details || typeof details !== "object" || Array.isArray(details)) {
    throw new TypeError("golden journey details must be an object");
  }
  const normalized = {};
  for (const [key, value] of Object.entries(details)) {
    if (!SAFE_DETAIL_KEYS.has(key)) {
      throw new TypeError(`golden journey detail key is not allowed: ${key}`);
    }
    if (
      key.endsWith("_count") ||
      key === "viewport_width" ||
      key === "viewport_height"
    ) {
      if (!Number.isInteger(value) || value < 0 || value > 100_000) {
        throw new TypeError(`golden journey detail value is invalid: ${key}`);
      }
    } else if (!SAFE_DETAIL_VALUES[key]?.has(value)) {
      throw new TypeError(`golden journey detail value is invalid: ${key}`);
    }
    normalized[key] = value;
  }
  return Object.freeze(normalized);
}

function assertOpaqueRef(key, value) {
  if (!SAFE_OPAQUE_REF.test(String(value || ""))) {
    throw new TypeError(`golden journey ${key} must be an opaque identifier`);
  }
}

function requireTimestamp(value, field) {
  const normalized = String(value || "");
  if (!normalized || Number.isNaN(Date.parse(normalized))) {
    throw new TypeError(`golden journey ${field} is invalid`);
  }
  return new Date(normalized).toISOString();
}

function assertMonotonicTimestamp(previous, next) {
  if (Date.parse(next) < Date.parse(previous)) {
    throw new TypeError("golden journey timestamp moved backwards");
  }
}

function freezeState(state) {
  return Object.freeze({
    ...state,
    completed_stages: Object.freeze([...state.completed_stages]),
    events: Object.freeze([...state.events])
  });
}
