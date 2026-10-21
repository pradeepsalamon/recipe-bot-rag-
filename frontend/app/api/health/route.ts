import { API_URL, unreachable } from "@/lib/backend";

export async function GET() {
  try {
    const upstream = await fetch(`${API_URL}/api/health`, { cache: "no-store" });
    return Response.json(await upstream.json(), { status: upstream.status });
  } catch {
    return unreachable();
  }
}
