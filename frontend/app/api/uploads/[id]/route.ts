import { backendUrl, unreachable } from "@/lib/backend";

export async function DELETE(_req: Request, ctx: RouteContext<"/api/uploads/[id]">) {
  const { id } = await ctx.params;
  try {
    const upstream = await fetch(backendUrl(`api/uploads/${encodeURIComponent(id)}`), { method: "DELETE" });
    return Response.json(await upstream.json(), { status: upstream.status });
  } catch {
    return unreachable();
  }
}
