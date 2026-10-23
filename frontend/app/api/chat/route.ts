import { backendUrl, unreachable } from "@/lib/backend";

// Pass the NDJSON event stream straight through so tool calls show as they happen.
export async function POST(request: Request) {
  let upstream: Response;
  try {
    upstream = await fetch(backendUrl("api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
    });
  } catch {
    return unreachable();
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-cache, no-transform",
    },
  });
}
