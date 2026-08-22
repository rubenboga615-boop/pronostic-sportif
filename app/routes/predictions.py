"""Routes des prédictions."""

from fastapi import APIRouter

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/")
async def list_predictions():
    """Lister les prédictions récentes."""
    return {"predictions": [], "message": "À implémenter"}


@router.get("/{match_id}")
async def get_prediction(match_id: int):
    """Obtenir la prédiction pour un match."""
    return {"match_id": match_id, "predictions": [], "message": "À implémenter"}
