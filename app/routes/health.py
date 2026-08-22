"""Route de santé de l'API."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Vérification de santé."""
    return {"status": "healthy"}
