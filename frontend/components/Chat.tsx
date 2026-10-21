"use client";

import { useEffect, useRef, useState } from "react";
import { askStream } from "@/lib/stream";
import type { Message, StreamEvent } from "@/lib/types";
import AssistantMessage from "./AssistantMessage";
import Composer from "./Composer";
import RecipeDrawer from "./RecipeDrawer";

const SUGGESTIONS = [
  "What can I make with rice and lemons? My kid is allergic to nuts.",
  "Is the shortbread safe for my son? He has a nut allergy.",
  "Scale the banana bread to 2 loaves.",
  "What temperature should roast chicken reach inside?",
];

type Health = { status: string; release?: string; model?: string; tools?: string[]; detail?: string };

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [openRecipe, setOpenRecipe] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const sessionId = useRef<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: "down" }));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function updateAssistant(id: string, fn: (m: Extract<Message, { role: "assistant" }>) => Partial<Message>) {
    setMessages((ms) =>
      ms.map((m) => (m.id === id && m.role === "assistant" ? ({ ...m, ...fn(m) } as Message) : m)),
    );
  }

  async function send(question: string) {
    if (!sessionId.current) sessionId.current = `web_${newId()}`;
    const replyId = newId();
    setMessages((ms) => [
      ...ms,
      { id: newId(), role: "user", text: question },
      { id: replyId, role: "assistant", steps: [], pending: true },
    ]);
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const onEvent = (e: StreamEvent) => {
      if (e.type === "final") updateAssistant(replyId, () => ({ final: e, pending: false }));
      else if (e.type === "error") updateAssistant(replyId, () => ({ error: e.message, pending: false }));
      else updateAssistant(replyId, (m) => ({ steps: [...m.steps, e] }));
    };

    try {
      await askStream(question, sessionId.current, onEvent, ctrl.signal);
      updateAssistant(replyId, (m) => (m.pending ? { pending: false, error: "The answer stream ended early." } : {}));
    } catch (err) {
      const aborted = ctrl.signal.aborted;
      updateAssistant(replyId, () => ({
        pending: false,
        error: aborted ? "Stopped." : err instanceof Error ? err.message : "Something went wrong.",
      }));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  function reset() {
    abortRef.current?.abort();
    setMessages([]);
    sessionId.current = "";
  }

  const down = health && health.status !== "ok";

  return (
    <div className="flex h-full flex-col">
      <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-accent text-lg text-white">🍲</div>
          <div className="min-w-0 flex-1">
            <h1 className="text-base font-semibold leading-tight">Pantry-to-Plate</h1>
            <p className="truncate text-xs text-muted">
              Answers only from the recipe library · allergens checked from the declarations
            </p>
          </div>
          <StatusPill health={health} />
          {messages.length > 0 && (
            <button
              onClick={reset}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted hover:bg-surface-muted hover:text-foreground"
            >
              New chat
            </button>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {down && (
            <div className="mb-4 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
              {health?.detail ?? "The Pantry API is not running."}
            </div>
          )}

          {messages.length === 0 ? (
            <EmptyState onPick={send} disabled={busy} />
          ) : (
            <div className="space-y-6">
              {messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-[15px] text-white">
                      {m.text}
                    </div>
                  </div>
                ) : (
                  <AssistantMessage key={m.id} message={m} onOpenRecipe={setOpenRecipe} />
                ),
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      <Composer busy={busy} onSend={send} onStop={() => abortRef.current?.abort()} />

      <RecipeDrawer recipeKey={openRecipe} onClose={() => setOpenRecipe(null)} onOpen={setOpenRecipe} />
    </div>
  );
}

function StatusPill({ health }: { health: Health | null }) {
  if (!health) return null;
  const ok = health.status === "ok";
  return (
    <span
      title={ok ? `${health.model} · tools: ${health.tools?.join(", ")}` : "API unreachable"}
      className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium sm:inline-flex ${
        ok ? "bg-ok-soft text-ok" : "bg-danger-soft text-danger"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-ok" : "bg-danger"}`} />
      {ok ? `${health.release} · ${health.tools?.length ?? 0} tools` : "offline"}
    </span>
  );
}

function EmptyState({ onPick, disabled }: { onPick: (q: string) => void; disabled: boolean }) {
  return (
    <div className="pt-10 text-center sm:pt-16">
      <div className="text-4xl">🥘</div>
      <h2 className="mt-3 text-2xl font-semibold tracking-tight">What are we cooking?</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted">
        Tell me what&apos;s in the fridge, who you&apos;re cooking for and any allergies. Every answer cites the
        recipe version it came from.
      </p>
      <div className="mt-8 grid gap-2 text-left sm:grid-cols-2">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            disabled={disabled}
            onClick={() => onPick(q)}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-sm transition hover:border-accent/50 hover:bg-accent-soft disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
