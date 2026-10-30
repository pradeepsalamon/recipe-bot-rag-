"use client";

import { useRef, useState } from "react";

const MAX_CHARS = 1000; // matches config.MAX_QUESTION_CHARS on the API

export default function Composer({
  busy,
  onSend,
  onStop,
  onAttach,
}: {
  busy: boolean;
  onSend: (q: string) => void;
  onStop: () => void;
  onAttach?: (file: File) => void; // absent when the API has uploads off
}) {
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const q = text.trim();
  const tooLong = q.length > MAX_CHARS;

  function submit() {
    if (!q || busy || tooLong) return;
    onSend(q);
    setText("");
  }

  return (
    <div className="border-t border-border bg-background">
      <form
        className="mx-auto max-w-3xl px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 shadow-sm focus-within:border-accent/60">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            autoFocus
            placeholder="Ask about a recipe, an allergy, scaling, a substitution…"
            className="field-sizing-content max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-muted"
          />
          {onAttach && (
            <>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                aria-label="Add your recipes (PDF, DOCX, TXT or MD)"
                title="Add your recipes (PDF, DOCX, TXT or MD)"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border text-xl leading-none text-muted transition hover:bg-surface-muted hover:text-foreground"
              >
                +
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt,.md"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) onAttach(f);
                }}
              />
            </>
          )}
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              className="h-10 rounded-xl border border-border px-4 text-sm font-medium hover:bg-surface-muted"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!q || tooLong}
              className="h-10 rounded-xl bg-accent px-4 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-40"
            >
              Send
            </button>
          )}
        </div>
        <p className={`mt-1.5 px-2 text-xs ${tooLong ? "text-danger" : "text-muted"}`}>
          {tooLong
            ? `${q.length}/${MAX_CHARS} characters — please shorten the question.`
            : "Not medical advice. For reactions or symptoms, contact a doctor."}
        </p>
      </form>
    </div>
  );
}
