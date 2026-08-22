"""Point d'entrée de l'API FastAPI."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(
    title="Pronostic Sportif",
    description="Moteur probabiliste de pronostic football",
    version="0.1.0",
    debug=settings.app_debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Vérification de santé de l'API."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def root() -> dict[str, str]:
    """Point d'entrée principal."""
    return {
        "message": "Pronostic Sportif API",
        "docs": "/docs",
        "health": "/health",
    }
