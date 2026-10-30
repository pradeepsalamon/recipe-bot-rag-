import type { StreamEvent, UploadEvent } from "./types";

/** POST a question and call onEvent for each NDJSON line as it arrives. */
export async function askStream(
  question: string,
  sessionId: string,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  });
  await readNdjson(res, onEvent);
}

/** Upload one recipe file; onEvent gets progress per extraction call, then done or error. */
export async function uploadStream(file: File, onEvent: (e: UploadEvent) => void, signal?: AbortSignal) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/uploads", { method: "POST", body: form, signal });
  await readNdjson(res, onEvent);
}

async function readNdjson<T>(res: Response, onEvent: (e: T) => void) {
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : `Request failed (${res.status})`,
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line) as T);
    }
    if (done) break;
  }
}
