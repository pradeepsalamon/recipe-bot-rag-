"use client";

import { useEffect, useState } from "react";
import type { Recipe } from "@/lib/types";

export default function RecipeDrawer({
  recipeKey,
  onClose,
  onOpen,
}: {
  recipeKey: string | null;
  onClose: () => void;
  onOpen: (key: string) => void;
}) {
  const [loaded, setLoaded] = useState<{ key: string; recipe?: Recipe; error?: string } | null>(null);

  useEffect(() => {
    if (!recipeKey) return;
    let live = true;
    fetch(`/api/recipes/${encodeURIComponent(recipeKey)}`)
      .then(async (r) => {
        const body = await r.json();
        if (!live) return;
        setLoaded(r.ok ? { key: recipeKey, recipe: body } : { key: recipeKey, error: body.detail ?? "Not found" });
      })
      .catch(() => live && setLoaded({ key: recipeKey, error: "Could not load the recipe." }));
    return () => {
      live = false;
    };
  }, [recipeKey]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!recipeKey) return null;
  const current = loaded?.key === recipeKey ? loaded : null;
  const r = current?.recipe;

  return (
    <div className="fixed inset-0 z-20 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface shadow-xl">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold leading-snug">{r?.title ?? recipeKey}</h2>
            <p className="font-mono text-xs text-muted">{recipeKey}</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg px-2 py-1 text-muted hover:bg-surface-muted hover:text-foreground"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 text-sm">
          {!current && <p className="text-muted">Loading…</p>}
          {current?.error && <p className="text-danger">{current.error}</p>}
          {r && (
            <div className="space-y-5">
              {r.status === "superseded" && (
                <div className="rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-danger">
                  <strong>Superseded.</strong> Do not cook from this version.
                  {r.current_key && (
                    <>
                      {" "}
                      Current:{" "}
                      <button className="font-mono underline" onClick={() => onOpen(r.current_key!)}>
                        {r.current_key}
                      </button>
                    </>
                  )}
                </div>
              )}
              {r.reformulation_note && (
                <div className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2">{r.reformulation_note}</div>
              )}
              {r.description && <p className="text-muted">{r.description}</p>}

              <div className="grid grid-cols-2 gap-2">
                <Fact label="Contains" tone="danger" items={r.allergens} empty="none declared" />
                <Fact label="May contain" tone="warn" items={r.may_contain} empty="none declared" />
                <Fact label="Yield" text={`${r.yield.amount} ${r.yield.unit}`} />
                <Fact
                  label="Time"
                  text={[
                    r.prep_minutes != null && `prep ${r.prep_minutes} min`,
                    r.cook_minutes != null && `cook ${r.cook_minutes} min`,
                    r.rest_minutes && `rest ${r.rest_minutes} min`,
                    r.oven_c && `${r.oven_c}°C`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                />
              </div>

              {r.dietary_tags?.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {r.dietary_tags.map((t) => (
                    <span key={t} className="rounded-full bg-ok-soft px-2 py-0.5 text-xs text-ok">
                      {t}
                    </span>
                  ))}
                </div>
              )}

              <section>
                <h3 className="mb-2 font-semibold">Ingredients</h3>
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {r.ingredients.map((i, n) => (
                    <li key={n} className="flex items-baseline gap-3 px-3 py-1.5">
                      <span className="w-20 shrink-0 text-right font-mono text-xs text-muted">
                        {i.qty != null ? `${i.qty} ${i.unit}` : i.unit}
                      </span>
                      <span className="flex-1">{i.item}</span>
                      {i.allergens && i.allergens.length > 0 && (
                        <span className="text-[11px] font-medium text-danger">{i.allergens.join(", ")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h3 className="mb-2 font-semibold">Method</h3>
                <ol className="list-decimal space-y-1.5 pl-5 marker:text-muted">
                  {r.method.map((s, n) => (
                    <li key={n}>{s}</li>
                  ))}
                </ol>
              </section>

              {r.notes && (
                <section>
                  <h3 className="mb-1 font-semibold">Notes</h3>
                  <p className="text-muted">{r.notes}</p>
                </section>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Fact({
  label,
  text,
  items,
  empty,
  tone,
}: {
  label: string;
  text?: string;
  items?: string[];
  empty?: string;
  tone?: "danger" | "warn";
}) {
  const color = tone === "danger" ? "text-danger" : tone === "warn" ? "text-warn" : "";
  return (
    <div className="rounded-lg bg-surface-muted px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`font-medium ${items?.length ? color : ""}`}>
        {items ? (items.length ? items.join(", ") : empty) : text || "—"}
      </div>
    </div>
  );
}
