"use client";

import { Fragment, useState } from "react";
import type { Citation, Message, Step } from "@/lib/types";

type Assistant = Extract<Message, { role: "assistant" }>;

const TOOL_LABELS: Record<string, string> = {
  search_recipes: "Searched the library",
  match_pantry: "Matched your pantry",
  get_recipe: "Opened recipe",
  check_allergens: "Checked allergens",
  scale_recipe: "Scaled quantities",
  find_substitution: "Looked up substitutions",
  safe_temperature: "Checked safe temperature",
};

// same pattern as pantry/agent.py _CITATION
const CITATION = /\[([a-z0-9_]+@[a-z0-9-]+)\]/g;

export default function AssistantMessage({
  message,
  onOpenRecipe,
}: {
  message: Assistant;
  onOpenRecipe: (key: string) => void;
}) {
  const { final, steps, pending, error } = message;
  const [showSteps, setShowSteps] = useState(false);
  const stepsOpen = pending || showSteps;
  const byKey = new Map(final?.citations.map((c) => [c.key, c]));

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-soft text-sm">🍲</div>
      <div className="min-w-0 flex-1 space-y-3">
        {(steps.length > 0 || pending) && (
          <div className="rounded-xl border border-border bg-surface-muted/60 text-sm">
            <button
              type="button"
              onClick={() => setShowSteps((s) => !s)}
              disabled={pending}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted"
            >
              {pending ? <Dots /> : <span className="text-xs">{stepsOpen ? "▾" : "▸"}</span>}
              <span className="flex-1">
                {pending
                  ? steps.length
                    ? stepLabel(steps[steps.length - 1]) + "…"
                    : "Thinking…"
                  : `${steps.length} step${steps.length === 1 ? "" : "s"}`}
              </span>
              {!pending && steps.some((s) => s.type === "tool" && s.name === "check_allergens") && (
                <span className="rounded-full bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">
                  allergens checked
                </span>
              )}
            </button>
            {stepsOpen && steps.length > 0 && (
              <ol className="space-y-1.5 border-t border-border px-3 py-2">
                {steps.map((s, i) => (
                  <StepRow key={i} step={s} />
                ))}
              </ol>
            )}
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>
        )}

        {final && (
          <>
            <div
              className={`rounded-2xl rounded-tl-md border px-4 py-3 text-[15px] leading-relaxed ${
                final.refused ? "border-warn/40 bg-warn-soft" : "border-border bg-surface"
              }`}
            >
              {final.refused && (
                <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-warn">
                  Could not recommend
                </div>
              )}
              <p className="whitespace-pre-wrap">
                <AnswerText text={final.answer} byKey={byKey} onOpen={onOpenRecipe} />
              </p>
            </div>

            {final.citations.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {final.citations.map((c) => (
                  <SourceCard key={c.key} c={c} onOpen={onOpenRecipe} />
                ))}
              </div>
            )}

            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
              {final.cached && <span className="font-medium text-ok">served from cache</span>}
              <span>{(final.latency_ms / 1000).toFixed(1)} s</span>
              <span>${final.cost_usd.toFixed(5)}</span>
              <span>
                {final.tokens_in}+{final.tokens_out} tokens
              </span>
              {final.terminated_by && <span className="text-warn">stopped: {final.terminated_by}</span>}
              <span className="font-mono" title="python run.py trace <id>">
                trace {final.trace_id.slice(0, 12)}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function stepLabel(s: Step) {
  return s.type === "validator" ? "Rechecking the answer" : (TOOL_LABELS[s.name] ?? s.name.replaceAll("_", " "));
}

function StepRow({ step }: { step: Step }) {
  const allergen = step.type === "tool" && step.name === "check_allergens";
  return (
    <li className="flex gap-2">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${allergen ? "bg-ok" : "bg-muted/60"}`} />
      <div className="min-w-0">
        <span className={allergen ? "font-medium text-ok" : "text-foreground"}>{stepLabel(step)}</span>
        {step.type === "tool" && Object.keys(step.args).length > 0 && (
          <span className="ml-1.5 break-all font-mono text-xs text-muted">{formatArgs(step.args)}</span>
        )}
        <div className="break-words text-xs text-muted">→ {step.summary}</div>
      </div>
    </li>
  );
}

function formatArgs(args: Record<string, unknown>) {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" ");
}

function AnswerText({
  text,
  byKey,
  onOpen,
}: {
  text: string;
  byKey: Map<string, Citation>;
  onOpen: (key: string) => void;
}) {
  const parts = text.split(CITATION); // odd indexes are citation keys
  return parts.map((part, i) =>
    i % 2 === 0 ? (
      <Fragment key={i}>{part}</Fragment>
    ) : (
      <button
        key={i}
        type="button"
        onClick={() => onOpen(part)}
        title={byKey.get(part)?.title ?? part}
        className={`mx-0.5 inline-flex items-center rounded-md px-1.5 py-px align-baseline font-mono text-[12px] hover:underline ${
          byKey.get(part)?.status === "superseded"
            ? "bg-danger-soft text-danger"
            : byKey.get(part)?.status === "invalid"
              ? "bg-surface-muted text-muted line-through"
              : "bg-accent-soft text-accent"
        }`}
      >
        {part}
      </button>
    ),
  );
}

function SourceCard({ c, onOpen }: { c: Citation; onOpen: (key: string) => void }) {
  const invalid = c.status === "invalid";
  const superseded = c.status === "superseded";
  return (
    <button
      type="button"
      disabled={invalid}
      onClick={() => onOpen(c.key)}
      className={`max-w-full rounded-xl border px-3 py-2 text-left text-sm transition ${
        superseded
          ? "border-danger/40 bg-danger-soft hover:border-danger"
          : invalid
            ? "border-border bg-surface-muted opacity-70"
            : "border-border bg-surface hover:border-accent/50"
      }`}
    >
      <div className="truncate font-medium">{c.title ?? "Not in the library"}</div>
      <div className="truncate font-mono text-xs text-muted">{c.key}</div>
      {superseded && (
        <div className="mt-0.5 text-xs font-medium text-danger">
          Superseded{c.current_key ? ` — current is ${c.current_key}` : ""}
        </div>
      )}
    </button>
  );
}

function Dots() {
  return (
    <span className="inline-flex gap-0.5">
      <span className="dot h-1.5 w-1.5 rounded-full bg-accent" />
      <span className="dot h-1.5 w-1.5 rounded-full bg-accent" />
      <span className="dot h-1.5 w-1.5 rounded-full bg-accent" />
    </span>
  );
}
