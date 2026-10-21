import { API_URL, unreachable } from "@/lib/backend";

export async function GET(_req: Request, ctx: RouteContext<"/api/recipes/[key]">) {
  const { key } = await ctx.params;
  try {
    const upstream = await fetch(`${API_URL}/api/recipes/${encodeURIComponent(key)}`);
    return Response.json(await upstream.json(), { status: upstream.status });
  } catch {
    return unreachable();
  }
}
