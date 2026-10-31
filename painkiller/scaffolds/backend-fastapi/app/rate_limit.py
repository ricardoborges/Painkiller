"""Limite de requisições por IP, em memória (uma instância do backend)."""

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

WINDOW_SECONDS = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int = 60, exempt: tuple[str, ...] = ()):
        super().__init__(app)
        self.per_minute = per_minute
        self.exempt = exempt
        self.hits: dict[str, deque] = defaultdict(deque)

    @staticmethod
    def _client(request: Request) -> str:
        # Atrás do proxy do deploy, o IP real vem no X-Forwarded-For.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "?"

    async def dispatch(self, request: Request, call_next):
        if self.per_minute <= 0 or request.method == "OPTIONS" or request.url.path in self.exempt:
            return await call_next(request)
        now = time.monotonic()
        hits = self.hits[self._client(request)]
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.per_minute:
            return JSONResponse({"detail": "Too many requests"}, status_code=429)
        hits.append(now)
        return await call_next(request)
