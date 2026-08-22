"""Routes d'administration."""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/status")
async def admin_status():
    """État de l'application."""
    return {"status": "ok", "message": "À implémenter"}
