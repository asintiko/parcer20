"""
FastAPI Main Application
Entry point for REST API
"""
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import os
from dotenv import load_dotenv

load_dotenv()


# Rate limiting middleware
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter - 100 requests per minute per IP"""

    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests: dict = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        minute_ago = current_time - 60

        # Clean old requests
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if req_time > minute_ago
        ]

        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )

        self.requests[client_ip].append(current_time)
        return await call_next(request)


# Error handling middleware
class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return generic error messages"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as e:
            # Log the actual error for debugging
            print(f"Unhandled error: {type(e).__name__}: {e}")
            # Return generic error to client
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )


# Create FastAPI app
app = FastAPI(
    title="Uzbek Receipt Parser API",
    description="High-load financial transaction parsing system for Uzbek banking receipts",
    version="1.0.0"
)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware, requests_per_minute=100)

# Add error handling middleware
app.add_middleware(ErrorHandlingMiddleware)

# CORS configuration - use environment variable or sensible defaults
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []

# Default allowed origins (localhost only for development)
allowed_origins = [
    FRONTEND_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Add any additional origins from environment
if CORS_ORIGINS:
    allowed_origins.extend([origin.strip() for origin in CORS_ORIGINS if origin.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown"""
    # Startup
    print("🚀 Starting Uzbek Receipt Parser API...")

    from database.connection import init_db, SessionLocal
    from services.telegram_tdlib_manager import get_tdlib_manager
    from services.tg_auto_monitor_service import init_auto_monitor_service
    import asyncio

    init_db()
    print("✅ Database initialized")

    # Start TDLib auto-monitor in background
    manager = get_tdlib_manager()
    monitor_service = init_auto_monitor_service(manager=manager, session_factory=SessionLocal)
    asyncio.create_task(monitor_service.start())

    yield

    # Shutdown
    print("👋 Shutting down API...")


# Update app with lifespan
app.router.lifespan_context = lifespan


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Uzbek Receipt Parser",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    from database.connection import engine
    from sqlalchemy import text

    try:
        # Test database connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "error"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "version": "1.0.0"
    }


# Import and register routes
from api.routes import analytics, automation, auth, logs, reference, transactions, userbot, telegram_client

app.include_router(auth.router, tags=["Authentication"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(reference.router, prefix="/api/reference", tags=["Reference"])
app.include_router(logs.router, prefix="/api/logs", tags=["Logs"])
app.include_router(automation.router, tags=["Automation"])
app.include_router(userbot.router, tags=["Userbot"])
app.include_router(telegram_client.router, tags=["Telegram"])

