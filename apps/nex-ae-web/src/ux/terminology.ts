import { DEFAULT_LOCALE, message } from "../locales/messages.js";

export const BUSINESS_TERMS = Object.freeze(
  [
    "WORKSPACE",
    "HUMAN_GATE",
    "ARTIFACT",
    "READY_FOR_PROMPT",
    "DOCUMENT",
    "ATTACHMENT",
    "SOURCE",
    "RESULT",
    "PROJECT",
  ] as const,
);

export type BusinessTerm = (typeof BUSINESS_TERMS)[number];

export interface BusinessTermPresentation {
  readonly term: BusinessTerm | "UNKNOWN";
  readonly known: boolean;
  readonly labelKey: string;
  readonly label: string;
}

export interface TechnicalStateDetail {
  readonly label: string;
  readonly value: string;
}

const BUSINESS_TERM_SET: ReadonlySet<string> = new Set(BUSINESS_TERMS);

export function mapBusinessTerm(
  value: unknown,
  locale = DEFAULT_LOCALE,
): BusinessTermPresentation {
  const candidate = normalizeTerm(value);
  const known = candidate !== null && BUSINESS_TERM_SET.has(candidate);
  const term = known ? (candidate as BusinessTerm) : "UNKNOWN";
  const labelKey = `ux.term.${term.toLowerCase()}`;
  return Object.freeze({
    term,
    known,
    labelKey,
    label: message(labelKey, { locale }),
  });
}

export function projectTechnicalStateDetail(
  value: unknown,
  { enabled = false, locale = DEFAULT_LOCALE } = {},
): TechnicalStateDetail | null {
  if (!enabled) return null;
  const normalized = normalizeTerm(value);
  if (normalized === null || normalized.length > 64) return null;
  return Object.freeze({
    label: message("ux.term.technical_state", { locale }),
    value: normalized,
  });
}

function normalizeTerm(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim().toUpperCase().replaceAll(/[-\s]+/g, "_");
  return /^[A-Z0-9_]+$/.test(normalized) ? normalized : null;
}
