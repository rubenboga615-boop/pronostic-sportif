"""Routes des matchs."""

from fastapi import APIRouter

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("/")
async def list_matches():
    """Lister les matchs."""
    return {"matches": [], "message": "À implémenter"}


@router.get("/{match_id}")
async def get_match(match_id: int):
    """Obtenir un match."""
    return {"match_id": match_id, "message": "À implémenter"}
