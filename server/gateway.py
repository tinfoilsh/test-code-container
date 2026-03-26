import asyncio
import secrets
from enum import Enum

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class _GatewayState(Enum):
    UNCLAIMED = "unclaimed"
    CLAIMED = "claimed"


class _Gateway:
    def __init__(self):
        self.state = _GatewayState.UNCLAIMED
        self.token: str | None = None
        # asyncio.Lock() is safe at module level in Python 3.10+: it no longer
        # binds to a running event loop at construction time.
        self.lock = asyncio.Lock()


_gw = _Gateway()


async def perform_claim() -> str | None:
    """Generate and store a bearer token, transitioning to CLAIMED state.

    Returns the new token, or None if the server was already claimed.
    Thread-safe: concurrent callers are serialised by the lock; only one wins.
    """
    async with _gw.lock:
        if _gw.state is _GatewayState.CLAIMED:
            return None
        token = secrets.token_urlsafe(32)
        _gw.token = token
        _gw.state = _GatewayState.CLAIMED
        return token


def GatewayMiddleware(app: ASGIApp) -> ASGIApp:
    """Raw ASGI middleware implementing the UNCLAIMED/CLAIMED state machine.

    Uses raw ASGI (not BaseHTTPMiddleware) to avoid response-buffering issues
    with the streaming /execute endpoint.
    """

    async def middleware(scope: Scope, receive: Receive, send: Send) -> None:
        # Pass non-HTTP scopes (lifespan, websocket) straight through.
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        path = scope["path"]

        # /health is always reachable (container orchestration health checks).
        if path == "/health":
            await app(scope, receive, send)
            return

        if _gw.state is _GatewayState.UNCLAIMED:
            if path == "/claim" and scope["method"] == "POST":
                await app(scope, receive, send)
            else:
                resp = JSONResponse(
                    {"detail": "Server has not been claimed yet"}, status_code=403
                )
                await resp(scope, receive, send)
            return

        # --- CLAIMED state ---

        # /claim is permanently closed once claimed.
        if path == "/claim":
            resp = JSONResponse({"detail": "Not Found"}, status_code=404)
            await resp(scope, receive, send)
            return

        # All other routes require a valid Bearer token.
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode()
        if not auth.startswith("Bearer "):
            resp = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await resp(scope, receive, send)
            return

        if not secrets.compare_digest(auth[len("Bearer "):], _gw.token):
            resp = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await resp(scope, receive, send)
            return

        await app(scope, receive, send)

    return middleware
