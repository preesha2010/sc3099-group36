"""
SAIV Backend API - Module 2

See docs/API-SPECIFICATION.md for endpoint contracts.
Routers are mounted at /api/v1; /health stays unprefixed.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api_router import api_router
from app.core.config import get_settings
from app.db.session import init_db
from app.middleware.rate_limit import RateLimitMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SAIV Backend API",
    description="Secure Attendance & Identity Verification System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy"}
