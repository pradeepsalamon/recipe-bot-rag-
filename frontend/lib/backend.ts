// Server-only: where the Python API (app/run.py serve-api) listens.
// In Vercel, this is injected by the service binding into PANTRY_API_URL.
export const API_URL = (process.env.PANTRY_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

export function backendUrl(pathname: string): URL {
  const base = API_URL.endsWith("/") ? API_URL : `${API_URL}/`;
  const cleanPath = pathname.startsWith("/") ? pathname.slice(1) : pathname;
  return new URL(cleanPath, base);
}

export function unreachable() {
  return Response.json(
    {
      detail: `The Pantry API is not reachable at ${API_URL}. Start it with: cd app && python run.py serve-api`,
    },
    { status: 502 },
  );
}
