# app/routers/health.py
# Health check endpoint with detailed status

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

router = APIRouter(tags=["health"])

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    database: str
    timestamp: str
    uptime_seconds: Optional[float] = None

# Track startup time
_startup_time: Optional[datetime] = None

def set_startup_time():
    global _startup_time
    _startup_time = datetime.utcnow()

@router.get("", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for monitoring and frontend connectivity verification.
    Returns detailed status of backend services.
    """
    # Check database connectivity
    db_status = "connected"
    try:
        from app.db import get_db_connection
        conn = get_db_connection()
        conn.execute("SELECT 1")
        conn.close()
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Calculate uptime
    uptime = None
    if _startup_time:
        uptime = (datetime.utcnow() - _startup_time).total_seconds()

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        service="reconai-backend",
        version="1.0.0",
        environment=os.getenv("ENVIRONMENT", "development"),
        database=db_status,
        timestamp=datetime.utcnow().isoformat(),
        uptime_seconds=uptime,
    )

@router.get("/ping")
async def root():
    """Root endpoint - basic status check"""
    return {
        "status": "ok",
        "service": "reconai-backend",
        "version": "1.0.0"
    }
