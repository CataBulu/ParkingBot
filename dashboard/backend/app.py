"""Local dashboard backend for the parking bot (Starlette). Run: python dashboard/backend/app.py"""
import asyncio
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import aws_bot

HOST, PORT = "127.0.0.1", 8765
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
ALLOWED_ORIGINS = {f"http://{h}:{p}" for h in ("127.0.0.1", "localhost") for p in (PORT, 5173)}

_action_lock = asyncio.Lock()


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


async def _run_aws(fn, *args):
    try:
        return await run_in_threadpool(fn, *args), None
    except Exception as e:  # noqa: BLE001 - report AWS problems to the UI instead of a 500 page
        if aws_bot.is_auth_error(e):
            aws_bot.reset_clients()
            return None, _error(aws_bot.LOGIN_HINT, 401)
        return None, _error(f"{type(e).__name__}: {e}", 502)


async def status(request: Request):
    result, err = await _run_aws(aws_bot.build_status)
    return err or JSONResponse(result)


async def logs(request: Request):
    try:
        minutes = min(max(int(request.query_params.get("minutes", 60)), 5), 1440)
    except ValueError:
        return _error("minutes must be a number", 400)
    result, err = await _run_aws(aws_bot.get_logs, minutes)
    return err or JSONResponse({"minutes": minutes, "lines": result})


async def _action(request: Request, payload: dict):
    # Block cross-site requests: only this dashboard may trigger Lambda runs / Telegram messages.
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return _error("Forbidden origin", 403)
    if not request.headers.get("content-type", "").startswith("application/json"):
        return _error("Expected application/json", 415)
    if _action_lock.locked():
        return _error("Another action is still running", 409)
    async with _action_lock:
        result, err = await _run_aws(aws_bot.invoke, payload)
    return err or JSONResponse(result)


async def test_alert(request: Request):
    try:
        body = await request.json()
        repetitions = min(max(int(body.get("repetitions", 3)), 1), 10)
    except (ValueError, TypeError, AttributeError):
        return _error("Body must be JSON like {\"repetitions\": 3}", 400)
    return await _action(request, {"test": True, "repetitions": repetitions})


async def run_check(request: Request):
    return await _action(request, {})


routes = [
    Route("/api/status", status),
    Route("/api/logs", logs),
    Route("/api/actions/test-alert", test_alert, methods=["POST"]),
    Route("/api/actions/run-check", run_check, methods=["POST"]),
]
if DIST.is_dir():
    routes.append(Mount("/", StaticFiles(directory=DIST, html=True), name="frontend"))

app = Starlette(
    routes=routes,
    middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])],
)

if __name__ == "__main__":
    if not DIST.is_dir():
        print(f"Frontend not built yet ({DIST}). API only; run `npm run build` in dashboard/frontend.")
    print(f"Dashboard: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
