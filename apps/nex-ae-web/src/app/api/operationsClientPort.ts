export interface OperationsServiceProjection {
  readonly serviceId: string;
  readonly healthStatus: string;
  readonly readinessStatus: string;
  readonly version: string | null;
}

export interface OperationsSummaryProjection {
  readonly overallStatus: string;
  readonly services: readonly OperationsServiceProjection[];
  readonly runtime: Readonly<{
    databaseStatus: string;
    agentRuntimeStatus: string;
    providerRouteStatus: string;
  }>;
  readonly routes: readonly Readonly<{ routeId: string; method: string; path: string }>[];
}

export interface OperationsClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly getSummary: () => Promise<OperationsSummaryProjection>;
}

export class OperationsClientError extends Error {
  readonly status: string;
  readonly statusCode: number | null;
  readonly retryable: boolean;

  constructor(message: string, status = "OPERATIONS_REQUEST_FAILED", statusCode: number | null = null, retryable = false) {
    super(message);
    this.name = "OperationsClientError";
    this.status = status;
    this.statusCode = statusCode;
    this.retryable = retryable;
  }
}

export function createOperationsClient({
  mode,
  baseUrl = "",
  fetchImpl,
  summary = defaultMockSummary(),
}: {
  readonly mode: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
  readonly summary?: unknown;
}): OperationsClientPort {
  if (mode === "mock") {
    return Object.freeze({ clientMode: "mock" as const, async getSummary() { return projectOperationsSummary(summary); } });
  }
  if (typeof fetchImpl !== "function") throw new OperationsClientError("Fetch is unavailable.", "FETCH_UNAVAILABLE");
  return Object.freeze({
    clientMode: "fetch" as const,
    async getSummary() {
      let response: Response;
      try {
        response = await fetchImpl(`${baseUrl}/api/v1/web/operations/summary`, {
          credentials: "include",
          headers: { Accept: "application/json" },
        });
      } catch {
        throw new OperationsClientError("운영 정보를 불러오지 못했습니다.", "NETWORK_ERROR", null, true);
      }
      const payload = await readJson(response);
      if (!response.ok) {
        throw new OperationsClientError(
          response.status === 403 ? "운영 화면에 접근할 권한이 없습니다." : "운영 정보를 불러오지 못했습니다.",
          safeCode(payload.error_code),
          response.status,
          Boolean(payload.retryable || response.status >= 500),
        );
      }
      return projectOperationsSummary(payload);
    },
  });
}

export function projectOperationsSummary(value: unknown): OperationsSummaryProjection {
  if (!isObject(value) || value.operations_summary_schema_version !== "ae_web_operations_summary.v1" || !Array.isArray(value.services)) {
    throw new OperationsClientError("운영 정보 응답이 올바르지 않습니다.", "OPERATIONS_RESPONSE_INVALID");
  }
  const runtime = isObject(value.runtime) ? value.runtime : {};
  const routes = Array.isArray(value.safe_routes) ? value.safe_routes : [];
  return Object.freeze({
    overallStatus: safeCode(value.overall_status, "UNKNOWN"),
    services: Object.freeze(value.services.map(projectService)),
    runtime: Object.freeze({
      databaseStatus: safeCode(runtime.database_status, "UNKNOWN"),
      agentRuntimeStatus: safeCode(runtime.agent_runtime_status, "UNKNOWN"),
      providerRouteStatus: safeCode(runtime.provider_route_status, "UNKNOWN"),
    }),
    routes: Object.freeze(routes.map(projectRoute)),
  });
}

function projectService(value: unknown): OperationsServiceProjection {
  if (!isObject(value)) throw new OperationsClientError("서비스 운영 정보가 올바르지 않습니다.", "OPERATIONS_SERVICE_INVALID");
  return Object.freeze({
    serviceId: requiredRef(value.service_id, "service_id"),
    healthStatus: safeCode(value.health_status, "UNKNOWN"),
    readinessStatus: safeCode(value.readiness_status, "UNKNOWN"),
    version: safeVersion(value.version),
  });
}

function projectRoute(value: unknown) {
  if (!isObject(value)) throw new OperationsClientError("운영 경로 정보가 올바르지 않습니다.", "OPERATIONS_ROUTE_INVALID");
  const path = requiredText(value.path, "path");
  if (!path.startsWith("/api/v1/")) throw new OperationsClientError("운영 경로가 안전하지 않습니다.", "OPERATIONS_ROUTE_UNSAFE");
  return Object.freeze({ routeId: requiredRef(value.route_id, "route_id"), method: safeCode(value.method, "GET"), path });
}

function defaultMockSummary() {
  return {
    operations_summary_schema_version: "ae_web_operations_summary.v1",
    overall_status: "READY",
    services: [{ service_id: "nex-ae-api", health_status: "HEALTHY", readiness_status: "READY", version: null }],
    runtime: { database_status: "AVAILABLE", agent_runtime_status: "AVAILABLE", provider_route_status: "CONFIGURED" },
    safe_routes: [{ route_id: "ae-web-operations-summary", method: "GET", path: "/api/v1/web/operations/summary" }],
  };
}

function requiredRef(value: unknown, field: string) {
  const normalized = requiredText(value, field);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(normalized)) throw new OperationsClientError(`${field} 값이 올바르지 않습니다.`, "OPERATIONS_REF_INVALID");
  return normalized;
}

function requiredText(value: unknown, field: string) {
  if (typeof value !== "string" || !value.trim()) throw new OperationsClientError(`${field} 값이 필요합니다.`, "OPERATIONS_RESPONSE_INVALID");
  return value.trim();
}

function safeVersion(value: unknown) {
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim();
  return normalized.length <= 48 && !/[\\/:@]/.test(normalized) ? normalized : null;
}

function safeCode(value: unknown, fallback = "OPERATIONS_REQUEST_FAILED") {
  const candidate = typeof value === "string" ? value.trim().toUpperCase() : "";
  return /^[A-Z][A-Z0-9_.-]{0,95}$/.test(candidate) ? candidate : fallback;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await response.json();
    return isObject(value) ? value : {};
  } catch {
    return {};
  }
}
