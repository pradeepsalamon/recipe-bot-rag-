export type Citation = {
  key: string;
  title: string | null;
  status: "current" | "superseded" | "invalid";
  current_key?: string | null;
};

export type ToolEvent = { type: "tool"; name: string; args: Record<string, unknown>; summary: string };
export type ValidatorEvent = { type: "validator"; summary: string };
export type FinalEvent = {
  type: "final";
  answer: string;
  citations: Citation[];
  refused: boolean;
  cached: boolean;
  trace_id: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  terminated_by: string | null;
};
export type ErrorEvent = { type: "error"; message: string };
export type StreamEvent = ToolEvent | ValidatorEvent | FinalEvent | ErrorEvent;

export type Step = ToolEvent | ValidatorEvent;

export type Message =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      steps: Step[];
      final?: FinalEvent;
      error?: string;
      pending: boolean;
    };

export type Recipe = Citation & {
  recipe_id: string;
  version: string;
  description?: string;
  cuisine?: string;
  dietary_tags: string[];
  allergens: string[];
  may_contain: string[];
  reformulation_note?: string;
  superseded_by?: string;
  yield: { amount: number; unit: string };
  prep_minutes?: number;
  cook_minutes?: number;
  rest_minutes?: number;
  oven_c?: number;
  ingredients: { item: string; qty: number | null; unit: string; allergens?: string[] }[];
  method: string[];
  notes?: string;
};
