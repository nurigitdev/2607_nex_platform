export type BusinessJourneyStepStatus =
  | "COMPLETED"
  | "CURRENT"
  | "AVAILABLE"
  | "UPCOMING"
  | "RETURNED"
  | "REJECTED"
  | "CANCELLED"
  | "BLOCKED";

export interface BusinessJourneyStep {
  readonly order: number;
  readonly code: string;
  readonly label: string;
  readonly status: BusinessJourneyStepStatus;
}

export interface BusinessJourney {
  readonly schema_version: "eos_business_journey.v1";
  readonly journey_kind: "BUSINESS_PROPOSAL" | "ACCOUNTING_VOUCHER";
  readonly current_stage: string;
  readonly terminal: boolean;
  readonly approval_stage_count: number | null;
  readonly steps: readonly BusinessJourneyStep[];
}

export function projectBusinessJourney(value: unknown): BusinessJourney {
  if (!isObject(value) || value.schema_version !== "eos_business_journey.v1" || !Array.isArray(value.steps)) {
    throw new TypeError("Business journey response is invalid.");
  }
  const journeyKind = text(value.journey_kind);
  if (journeyKind !== "BUSINESS_PROPOSAL" && journeyKind !== "ACCOUNTING_VOUCHER") {
    throw new TypeError("Business journey kind is invalid.");
  }
  return Object.freeze({
    schema_version: "eos_business_journey.v1" as const,
    journey_kind: journeyKind,
    current_stage: text(value.current_stage),
    terminal: value.terminal === true,
    approval_stage_count: value.approval_stage_count === null ? null : integer(value.approval_stage_count),
    steps: value.steps.map((step, index) => projectStep(step, index + 1)),
  });
}

function projectStep(value: unknown, expectedOrder: number): BusinessJourneyStep {
  if (!isObject(value)) throw new TypeError("Business journey step is invalid.");
  const order = integer(value.order);
  const status = text(value.status) as BusinessJourneyStepStatus;
  const statuses: readonly BusinessJourneyStepStatus[] = [
    "COMPLETED", "CURRENT", "AVAILABLE", "UPCOMING", "RETURNED", "REJECTED", "CANCELLED", "BLOCKED",
  ];
  if (order !== expectedOrder || !statuses.includes(status)) {
    throw new TypeError("Business journey step order or status is invalid.");
  }
  return Object.freeze({ order, code: text(value.code), label: text(value.label), status });
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) throw new TypeError("Business journey text is invalid.");
  return value.trim();
}

function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new TypeError("Business journey integer is invalid.");
  }
  return value;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
