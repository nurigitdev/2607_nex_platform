export class BrowserRequestBoundaryError extends Error {
  readonly status: string;

  constructor(message: string, status: string) {
    super(message);
    this.name = "BrowserRequestBoundaryError";
    this.status = status;
  }
}

export function assertSameOriginAeRequest(
  input: RequestInfo | URL,
  browserOrigin = globalThis.location?.origin,
) {
  if (!browserOrigin) {
    throw new BrowserRequestBoundaryError(
      "Browser origin is required.",
      "BROWSER_ORIGIN_REQUIRED",
    );
  }
  const rawUrl = input instanceof Request ? input.url : String(input);
  const resolved = new URL(rawUrl, browserOrigin);
  if (resolved.origin !== browserOrigin) {
    throw new BrowserRequestBoundaryError(
      "Cross-origin business request is blocked.",
      "CROSS_ORIGIN_REQUEST_BLOCKED",
    );
  }
  if (resolved.pathname !== "/ae-api" && !resolved.pathname.startsWith("/ae-api/")) {
    throw new BrowserRequestBoundaryError(
      "Business request must use the AE facade.",
      "NON_AE_REQUEST_BLOCKED",
    );
  }
  return resolved;
}

export function createSameOriginAeFetch({
  fetchImpl = globalThis.fetch,
  browserOrigin = globalThis.location?.origin,
}: {
  readonly fetchImpl?: typeof globalThis.fetch;
  readonly browserOrigin?: string;
} = {}): typeof globalThis.fetch {
  if (typeof fetchImpl !== "function") {
    throw new BrowserRequestBoundaryError("fetch is unavailable.", "FETCH_UNAVAILABLE");
  }
  return ((input: RequestInfo | URL, init?: RequestInit) => {
    assertSameOriginAeRequest(input, browserOrigin);
    return fetchImpl(input, init);
  }) as typeof globalThis.fetch;
}
