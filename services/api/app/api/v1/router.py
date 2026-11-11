"""Aggregate API v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, identity

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(identity.router)
