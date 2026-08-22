"""Schémas Pydantic pour les requêtes et réponses de l'API."""

from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str


class MatchResponse(BaseModel):
    id: int
    match_date: datetime | None
    home_team: str | None
    away_team: str | None
    home_goals: int | None
    away_goals: int | None
    competition: str | None


class PredictionResponse(BaseModel):
    match_id: int
    market: str
    selection: str
    probability: float
    fair_odds: float
    offered_odds: float | None
    edge: float | None
    model_version: str
    generated_at: datetime
    data_quality: float


class SourceHealthResponse(BaseModel):
    source: str
    status: str
    last_success_at: datetime | None
    last_error: str | None
    quota_remaining: int | None


class PredictionRequest(BaseModel):
    home_team: str
    away_team: str
    match_date: datetime | None = None
    competition: str | None = None
