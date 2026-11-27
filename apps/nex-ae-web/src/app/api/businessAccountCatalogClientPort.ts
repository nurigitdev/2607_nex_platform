export interface BusinessAccountOption {
  readonly account_code: string;
  readonly account_name: string;
  readonly category: string;
  readonly account_type: string;
}

export interface BusinessAccountCatalog {
  readonly company_id: string;
  readonly effective_on: string;
  readonly transaction_currency: string;
  readonly accounts: readonly BusinessAccountOption[];
}

export interface BusinessAccountCatalogQuery {
  readonly companyId: string;
  readonly effectiveOn: string;
  readonly transactionCurrency: string;
}

export interface BusinessAccountCatalogClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly get: (input: BusinessAccountCatalogQuery) => Promise<BusinessAccountCatalog>;
}

export class BusinessAccountCatalogClientError extends Error {
  readonly status: string;
  readonly statusCode: number | null;

  constructor(message: string, status = "BUSINESS_ACCOUNT_CATALOG_REQUEST_FAILED", statusCode: number | null = null) {
    super(message);
    this.name = "BusinessAccountCatalogClientError";
    this.status = status;
    this.statusCode = statusCode;
  }
}

export function createBusinessAccountCatalogClient({
  mode,
  baseUrl = "",
  fetchImpl,
}: {
  readonly mode: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
}): BusinessAccountCatalogClientPort {
  if (mode === "mock") {
    return Object.freeze({
      clientMode: "mock" as const,
      async get(input: BusinessAccountCatalogQuery) {
        return Object.freeze({
          company_id: input.companyId,
          effective_on: input.effectiveOn,
          transaction_currency: input.transactionCurrency,
          accounts: Object.freeze([]),
        });
      },
    });
  }
  if (typeof fetchImpl !== "function") {
    throw new BusinessAccountCatalogClientError("Fetch is unavailable.", "FETCH_UNAVAILABLE");
  }
  return Object.freeze({
    clientMode: "fetch" as const,
    async get(input: BusinessAccountCatalogQuery) {
      const query = new URLSearchParams({
        company_id: input.companyId,
        effective_on: input.effectiveOn,
        transaction_currency: input.transactionCurrency,
      });
      const response = await fetchImpl(`${baseUrl}/api/v1/business-account-catalog?${query}`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new BusinessAccountCatalogClientError(
          text(payload.detail, "계정과목을 불러오지 못했습니다."),
          text(payload.error_code, "BUSINESS_ACCOUNT_CATALOG_REQUEST_FAILED"),
          response.status,
        );
      }
      return projectCatalog(payload);
    },
  });
}

function projectCatalog(value: Record<string, unknown>): BusinessAccountCatalog {
  if (value.schema_version !== "ae_business_account_catalog.v1" || !Array.isArray(value.accounts)) {
    throw invalidResponse();
  }
  return Object.freeze({
    company_id: requiredText(value.company_id),
    effective_on: requiredText(value.effective_on),
    transaction_currency: requiredText(value.transaction_currency),
    accounts: Object.freeze(value.accounts.map(projectAccount)),
  });
}

function projectAccount(value: unknown): BusinessAccountOption {
  if (!isObject(value)) throw invalidResponse();
  return Object.freeze({
    account_code: requiredText(value.account_code),
    account_name: requiredText(value.account_name),
    category: text(value.category),
    account_type: text(value.account_type),
  });
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await response.json();
    if (!isObject(value)) throw invalidResponse();
    return value;
  } catch (error) {
    if (error instanceof BusinessAccountCatalogClientError) throw error;
    throw invalidResponse();
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function text(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function requiredText(value: unknown): string { const result = text(value); if (!result) throw invalidResponse(); return result; }
function invalidResponse() { return new BusinessAccountCatalogClientError("계정과목 응답 형식이 올바르지 않습니다.", "INVALID_RESPONSE", 502); }
