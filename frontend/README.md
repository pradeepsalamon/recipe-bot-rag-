# Pantry-to-Plate web chat

Next.js chat UI for the Week 12 Pantry-to-Plate assistant in [`../app`](../app).

## Run

Two processes:

```bash
# 1. the Python API (from the repo root)
cd app
python run.py serve-api            # http://127.0.0.1:8000

# 2. the UI
cd frontend
npm install
npm run dev                        # http://localhost:3000
```

The UI talks to its own `/api/*` route handlers, which proxy to the Python API, so there is no CORS setup.
Set `PANTRY_API_URL` (in `frontend/.env.local`) if the API runs somewhere other than `http://127.0.0.1:8000`.

## What it shows

- Tool calls stream in as the agent makes them (`POST /api/chat` returns NDJSON). The allergen check is highlighted.
- Inline `[recipe@version]` citations and source cards open the recipe-version card. Superseded versions are flagged in red and link to the current version.
- Refusals are styled differently. Each answer shows its latency, cost, tokens and trace id (`python run.py trace <id>`).

| File | What |
|---|---|
| `components/Chat.tsx` | Conversation state, session id, streaming |
| `components/AssistantMessage.tsx` | Steps, answer with citation chips, sources, metadata |
| `components/RecipeDrawer.tsx` | Recipe-version card |
| `app/api/*/route.ts` | Proxies to the Python API |
| `../app/pantry/api.py` | The FastAPI side (`python run.py serve-api`) |
