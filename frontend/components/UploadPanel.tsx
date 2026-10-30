"use client";

import { type Ref, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { uploadStream } from "@/lib/stream";
import type { UploadedFile, UploadResult } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.txt,.md"; // matches config.UPLOAD_LIMITS on the API
const MAX_MB = 20;

type Progress = { filename: string; done: number; total: number };

/** Lets the composer's + button hand a file straight to the panel. */
export type UploadHandle = { upload: (file: File) => void };

export default function UploadPanel({
  open,
  onClose,
  onOpenRecipe,
  ref,
}: {
  open: boolean;
  onClose: () => void;
  onOpenRecipe: (key: string) => void;
  ref?: Ref<UploadHandle>;
}) {
  const [files, setFiles] = useState<UploadedFile[] | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    fetch("/api/uploads")
      .then(async (r) => {
        const body = await r.json();
        if (r.ok) setFiles(body.files);
        else setError(body.detail ?? "Could not list uploads.");
      })
      .catch(() => setError("Could not list uploads."));
  }, []);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function upload(file: File) {
    setError(null);
    setResult(null);
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`${file.name} is over ${MAX_MB} MB.`);
      return;
    }
    setProgress({ filename: file.name, done: 0, total: 0 });
    try {
      await uploadStream(file, (e) => {
        if (e.type === "progress") setProgress({ filename: file.name, done: e.done, total: e.total });
        else if (e.type === "done") setResult(e);
        else setError(e.message);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setProgress(null);
      refresh();
    }
  }

  async function remove(f: UploadedFile) {
    if (!confirm(`Remove ${f.filename} and its ${f.recipes.length} recipe(s)?`)) return;
    const r = await fetch(`/api/uploads/${encodeURIComponent(f.file_id)}`, { method: "DELETE" });
    if (!r.ok) setError((await r.json().catch(() => null))?.detail ?? "Could not remove the file.");
    if (result?.file_id === f.file_id) setResult(null);
    refresh();
  }

  useImperativeHandle(ref, () => ({
    upload: (file: File) => (progress ? setError("Wait for the current upload to finish.") : upload(file)),
  }));

  if (!open) return null;
  const busy = progress !== null;
  const pct = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <div className="fixed inset-0 z-20 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface shadow-xl">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold leading-snug">Your recipes</h2>
            <p className="text-xs text-muted">Upload a recipe doc, PDF or cookbook and ask about it in the chat.</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg px-2 py-1 text-muted hover:bg-surface-muted hover:text-foreground"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-sm">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files[0];
              if (f && !busy) upload(f);
            }}
            className={`rounded-xl border-2 border-dashed px-4 py-6 text-center transition ${
              dragging ? "border-accent bg-accent-soft" : "border-border"
            }`}
          >
            {busy ? (
              <div>
                <p className="truncate font-medium">Reading {progress.filename}…</p>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-muted">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                </div>
                <p className="mt-1.5 text-xs text-muted">
                  {progress.total ? `section ${progress.done} of ${progress.total}` : "extracting text…"}
                </p>
              </div>
            ) : (
              <>
                <p className="font-medium">Drop a file here</p>
                <p className="mt-0.5 text-xs text-muted">PDF (text, not scanned), DOCX, TXT or MD · up to {MAX_MB} MB</p>
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  className="mt-3 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
                >
                  Choose file
                </button>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) upload(f);
              }}
            />
          </div>

          <div className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-xs">
            <strong>Allergens are not declared</strong> for uploaded recipes. The assistant will never call them safe
            for an allergy: check every ingredient and label yourself.
          </div>

          {error && (
            <div className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-danger">{error}</div>
          )}

          {result && (
            <div className="rounded-lg border border-ok/30 bg-ok-soft px-3 py-2">
              <p className="font-medium text-ok">
                {result.duplicate
                  ? `${result.filename} was already uploaded.`
                  : `Found ${result.recipes.length} recipe${result.recipes.length === 1 ? "" : "s"} in ${result.filename}.`}
              </p>
              {result.warnings.map((w) => (
                <p key={w} className="mt-1 text-xs text-warn">
                  {w}
                </p>
              ))}
              {result.skipped.length > 0 && (
                <p className="mt-1 text-xs text-muted">
                  Skipped {result.skipped.length} incomplete: {result.skipped.slice(0, 3).join("; ")}
                  {result.skipped.length > 3 ? "…" : ""}
                </p>
              )}
            </div>
          )}

          <section>
            <h3 className="mb-2 font-semibold">Uploaded files</h3>
            {files === null ? (
              <p className="text-muted">Loading…</p>
            ) : files.length === 0 ? (
              <p className="text-muted">Nothing uploaded yet.</p>
            ) : (
              <ul className="space-y-3">
                {files.map((f) => (
                  <li key={f.file_id} className="rounded-lg border border-border">
                    <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                      <span className="min-w-0 flex-1 truncate font-medium" title={f.filename}>
                        {f.filename}
                      </span>
                      <span className="text-xs text-muted">{f.recipes.length}</span>
                      <button
                        onClick={() => remove(f)}
                        disabled={busy}
                        className="rounded-md px-2 py-0.5 text-xs text-muted hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                      >
                        Remove
                      </button>
                    </div>
                    <ul className="divide-y divide-border">
                      {f.recipes.map((r) => (
                        <li key={r.key}>
                          <button
                            onClick={() => onOpenRecipe(r.key)}
                            className="block w-full truncate px-3 py-1.5 text-left hover:bg-surface-muted"
                          >
                            {r.title ?? r.key}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}
