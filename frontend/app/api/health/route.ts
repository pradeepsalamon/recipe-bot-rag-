import { backendUrl, unreachable } from "@/lib/backend";

export async function GET() {
  let upstream: Response;
  try {
    upstream = await fetch(backendUrl("api/health"), { cache: "no-store" });
  } catch {
    return unreachable();
  }
  // A crashed Python function answers with a plain-text/HTML 500, not JSON:
  // say so instead of reporting the API as unreachable.
  const text = await upstream.text();
  try {
    return Response.json(JSON.parse(text), { status: upstream.status });
  } catch {
    return Response.json(
      { status: "error", detail: `The Pantry API answered ${upstream.status}: ${text.slice(0, 300)}` },
      { status: 502 },
    );
  }
}
