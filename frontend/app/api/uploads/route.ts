import { backendUrl, unreachable } from "@/lib/backend";

// Forward the multipart body, then pass the NDJSON progress stream straight through.
export async function POST(request: Request) {
  let upstream: Response;
  try {
    upstream = await fetch(backendUrl("api/uploads"), { method: "POST", body: await request.formData() });
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

export async function GET() {
  try {
    const upstream = await fetch(backendUrl("api/uploads"), { cache: "no-store" });
    return Response.json(await upstream.json(), { status: upstream.status });
  } catch {
    return unreachable();
  }
}
