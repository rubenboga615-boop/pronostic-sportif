"""Routes des sources de données."""

from fastapi import APIRouter

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/health")
async def sources_health():
    """État de santé des sources de données."""
    return {"sources": [], "message": "À implémenter"}
