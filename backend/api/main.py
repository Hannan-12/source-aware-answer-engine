"""FastAPI wrapper around the search engine.

Exposes the same retrieve -> synthesize pipeline as the CLI, but over HTTP so a
frontend (e.g. a Next.js app on localhost:3000) can call it.

Run with:
    uvicorn api.main:app --reload

Then POST to /search:
    curl -X POST http://localhost:8000/search \
         -H "Content-Type: application/json" \
         -d '{"query": "what is retrieval augmented generation"}'
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from engine.errors import MissingAPIKeyError, SearchEngineError
from engine.retriever import search_web
from engine.synthesizer import synthesize_structured

# Load .env so the engine can read the required provider keys and config.
load_dotenv()

# Rate limiter keyed by client IP. This protects the free-tier Tavily/Groq
# quota from being drained by bots once the API is public. In-memory by
# default, which is fine for a single-instance deploy.
DEFAULT_LIMIT = os.getenv("RATE_LIMIT_REQUESTS", "10")
DEFAULT_WINDOW = os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
LIMIT_STRING = f"{DEFAULT_LIMIT}/{DEFAULT_WINDOW}seconds"
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Custom Search Engine",
    description="Perplexity-style search: a query in, a cited answer out.",
    version="1.0.0",
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Return a clean JSON message rather than slowapi's default, so the
    # frontend renders it in the interface's voice.
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many searches in a short time. Wait a moment and try again."
        },
    )

# Allow the frontend to call this API from the browser. Prefer the canonical
# FRONTEND_ORIGIN env var, but retain ALLOWED_ORIGINS for compatibility with the
# earlier local setup. Falls back to localhost for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _origin_list() -> list[str]:
    """Resolve the allowed frontend origins from the current env values."""
    raw = os.getenv("FRONTEND_ORIGIN") or os.getenv("ALLOWED_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000"]


ALLOWED_ORIGINS = _origin_list()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The question to answer.")
    num_results: int = Field(
        6, ge=1, le=20, description="How many sources to fetch."
    )


class Source(BaseModel):
    title: str
    url: str
    # The raw retrieved snippet that fed the LLM — surfaced for the
    # "show your work" view so users can see the retrieval step.
    snippet: str = ""


class SearchResponse(BaseModel):
    answer: str
    sources: list[Source]
    # How well the sources agree: "agree" | "mixed" | "single".
    agreement: str = "single"
    agreement_note: str = ""


@app.get("/health")
def health() -> dict:
    """Simple liveness check."""
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
@limiter.limit(LIMIT_STRING)
def search(request: Request, payload: SearchRequest) -> SearchResponse:
    """Retrieve sources for the query and return a synthesized cited answer."""
    try:
        results = search_web(payload.query, num_results=payload.num_results)
        if not results:
            raise HTTPException(status_code=404, detail="No results found.")
        synthesis = synthesize_structured(payload.query, results)
    except MissingAPIKeyError as exc:
        # Server misconfiguration (missing key) — 500, but with a clear message.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SearchEngineError as exc:
        # Retrieval/synthesis failure — 502 (upstream provider issue).
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    sources = [
        Source(title=r["title"], url=r["url"], snippet=r.get("snippet", ""))
        for r in results
    ]
    return SearchResponse(
        answer=synthesis["answer"],
        sources=sources,
        agreement=synthesis["agreement"],
        agreement_note=synthesis["agreement_note"],
    )
