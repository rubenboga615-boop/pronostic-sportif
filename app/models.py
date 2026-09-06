"""Modèles ORM de la base de données."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)

from app.database import Base


class Competition(Base):
    __tablename__ = "competitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    country = Column(String, nullable=False)
    provider_code = Column(String, unique=True, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Season(Base):
    __tablename__ = "seasons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    season_name = Column(String, nullable=False)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    status = Column(String, default="active")


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String, nullable=False)
    country = Column(String)
    provider = Column(String)
    provider_team_id = Column(String)
    active = Column(Boolean, default=True)


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String)
    provider_match_id = Column(String)
    competition_id = Column(Integer, ForeignKey("competitions.id"))
    season_id = Column(Integer, ForeignKey("seasons.id"))
    match_date = Column(DateTime)
    home_team_id = Column(Integer, ForeignKey("teams.id"))
    away_team_id = Column(Integer, ForeignKey("teams.id"))
    status = Column(String, default="scheduled")
    home_goals = Column(Integer)
    away_goals = Column(Integer)
    home_ht_goals = Column(Integer)
    away_ht_goals = Column(Integer)
    home_shots = Column(Integer)
    away_shots = Column(Integer)
    home_shots_on_target = Column(Integer)
    away_shots_on_target = Column(Integer)
    source_created_at = Column(DateTime)
    source_updated_at = Column(DateTime)


class TeamMatchStats(Base):
    __tablename__ = "team_match_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    shots = Column(Integer)
    shots_on_target = Column(Integer)
    shots_off_target = Column(Integer)
    corners = Column(Integer)
    fouls = Column(Integer)
    yellow_cards = Column(Integer)
    red_cards = Column(Integer)
    possession = Column(Float)
    passes = Column(Integer)
    accurate_passes = Column(Integer)
    source = Column(String)
    quality_status = Column(String, default="unknown")


class XgMatchStats(Base):
    __tablename__ = "xg_match_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    xg = Column(Float)
    xga = Column(Float)
    npxg = Column(Float)
    xa = Column(Float)
    shots = Column(Integer)
    source = Column(String)
    retrieved_at = Column(DateTime, default=datetime.utcnow)
    quality_status = Column(String, default="unknown")


class Availability(Base):
    __tablename__ = "availability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    player_id = Column(String)
    player_name = Column(String)
    status = Column(String, default="unknown")  # unknown, confirmed_absence, available
    reason = Column(String)
    confirmed = Column(Boolean, default=False)
    source = Column(String)
    retrieved_at = Column(DateTime, default=datetime.utcnow)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    bookmaker = Column(String)
    market = Column(String)
    selection = Column(String)
    odds = Column(Float)
    captured_at = Column(DateTime, default=datetime.utcnow)
    is_closing = Column(Boolean, default=False)
    source = Column(String)


class Feature(Base):
    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    calculated_at = Column(DateTime, default=datetime.utcnow)
    form_points_5 = Column(Float)
    form_points_10 = Column(Float)
    goals_for_avg_5 = Column(Float)
    goals_against_avg_5 = Column(Float)
    home_away_goals_for_avg = Column(Float)
    home_away_goals_against_avg = Column(Float)
    xg_avg_5 = Column(Float)
    xga_avg_5 = Column(Float)
    npxg_avg_5 = Column(Float)
    shots_avg_5 = Column(Float)
    shots_on_target_avg_5 = Column(Float)
    league_position = Column(Integer)
    goal_difference = Column(Integer)
    elo_rating = Column(Float)
    opponent_strength = Column(Float)
    rest_days = Column(Integer)
    injury_impact = Column(Float)
    odds_movement = Column(Float)
    data_completeness = Column(Float)


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    model_version = Column(String)
    generated_at = Column(DateTime, default=datetime.utcnow)
    market = Column(String)
    selection = Column(String)
    probability = Column(Float)
    fair_odds = Column(Float)
    offered_odds = Column(Float)
    edge = Column(Float)
    confidence = Column(Float)
    data_quality = Column(Float)
    status = Column(String, default="pending")


class ActualResult(Base):
    __tablename__ = "actual_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    market = Column(String)
    selection = Column(String)
    actual_outcome = Column(String)
    settled_at = Column(DateTime)


class SourceHealth(Base):
    __tablename__ = "source_health"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, unique=True, nullable=False)
    last_success_at = Column(DateTime)
    last_attempt_at = Column(DateTime)
    last_error = Column(String)
    records_last_run = Column(Integer)
    status = Column(String, default="unknown")  # healthy, degraded, failed, stale
    quota_remaining = Column(Integer)
