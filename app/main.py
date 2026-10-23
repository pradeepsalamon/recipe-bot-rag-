import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

try:
    from pantry.api import app
except Exception:
    # An import crash otherwise shows up only as Vercel's FUNCTION_INVOCATION_FAILED:
    # serve the traceback on every route so /api/health can show it.
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    _error = traceback.format_exc()
    print(_error, file=sys.stderr)
    app = FastAPI(title="Pantry-to-Plate API (import failed)")

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def _import_failed(path: str):
        return JSONResponse({"status": "error", "detail": f"Import failed: {_error[-1500:]}"}, status_code=500)

__all__ = ["app"]
