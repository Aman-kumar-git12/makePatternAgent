"""REST API: GET /health, GET /api/providers, POST /api/analyze."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .analyzer import AgentError, analyse_with_fallback, list_models
from .config import settings
from .prompt import Variable
from .providers import PROVIDERS

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_CODE_CHARS = 20_000


class AnalyzeRequest(BaseModel):
    provider: str = Field(default="groq", max_length=40)
    model: str = Field(default="", max_length=120)
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    language: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=200)


class AnalyzeResponse(BaseModel):
    provider: str
    model: str
    time_complexity: str
    space_complexity: str
    time_explanation: str
    space_explanation: str
    variables: list[Variable]
    is_optimal: bool
    better_complexity: str
    suggestion: str
    confidence: str


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        q = self.hits[client]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def create_app(http_client: httpx.AsyncClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = http_client or httpx.AsyncClient()
        yield
        if http_client is None:
            await app.state.http.aclose()

    app = FastAPI(title="MakePattern complexity agent", version="1.0.0", lifespan=lifespan)
    app.state.limiter = RateLimiter(settings.rate_limit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        # Browser extensions and local dev servers.
        allow_origin_regex=r"^(chrome-extension|moz-extension)://[a-z0-9-]+$|^http://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    )

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/providers")
    async def providers():
        return [p.public() for p in PROVIDERS.values()]

    @app.get("/api/models")
    async def models(
        provider: str,
        x_api_key: str | None = Header(default=None),
    ):
        """The chat models your key can use on a provider (for picking a model)."""
        p = PROVIDERS.get(provider)
        if p is None:
            raise HTTPException(400, f"Unknown provider '{provider}'.")
        key = (x_api_key or "").strip() or (os.getenv(p.env_key, "").strip() if p.env_key else "")
        if p.needs_key and not key:
            raise HTTPException(401, f"Paste your {p.name} API key first.")
        try:
            return {"provider": p.id, "models": await list_models(app.state.http, p, key)}
        except AgentError as e:
            raise HTTPException(e.status, e.message) from None

    @app.post("/api/analyze", response_model=AnalyzeResponse)
    async def analyze(
        body: AnalyzeRequest,
        request: Request,
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        if not app.state.limiter.allow(request.client.host if request.client else "?"):
            raise HTTPException(429, "Too many requests; wait a minute.")
        provider = PROVIDERS.get(body.provider)
        if provider is None:
            raise HTTPException(400, f"Unknown provider '{body.provider}'.")
        key = (x_api_key or "").strip()
        if not key and authorization and authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        if not key and provider.env_key:
            key = os.getenv(provider.env_key, "").strip()
        if provider.needs_key and not key:
            raise HTTPException(401, f"Paste your {provider.name} API key first.")
        if not body.code.strip():
            raise HTTPException(422, "Paste some code first.")
        model = body.model.strip() or provider.default_model
        try:
            model, result = await analyse_with_fallback(
                app.state.http, provider, key, model, bool(body.model.strip()), body.code, body.language, body.title
            )
        except AgentError as e:
            raise HTTPException(e.status, e.message) from None
        return AnalyzeResponse(
            provider=provider.id,
            model=model,
            time_complexity=result.time_complexity,
            space_complexity=result.space_complexity,
            time_explanation=result.time_explanation,
            space_explanation=result.space_explanation,
            variables=result.variables,
            is_optimal=result.is_optimal,
            better_complexity="" if result.is_optimal else result.better_complexity,
            suggestion=result.suggestion,
            confidence=result.confidence,
        )

    return app


app = create_app()
