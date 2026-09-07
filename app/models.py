"""Modèles ORM de la base de données."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)

from app.database import Base


def maintenant_utc() -> datetime:
    """Horodatage UTC par défaut des colonnes techniques.

    `datetime.utcnow()` est déprécié : il renvoie un datetime naïf qui prétend
    être local alors qu'il est UTC, un piège classique. La base stocke des
    datetimes naïfs, et les lignes déjà écrites le sont ; on retire donc le
    fuseau après coup plutôt que de mélanger, dans une même colonne, des
    valeurs naïves et des valeurs conscientes du fuseau.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Competition(Base):
    __tablename__ = "competitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    country = Column(String, nullable=False)
    provider_code = Column(String, unique=True, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=maintenant_utc)


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (Index("idx_seasons_lookup", "competition_id", "season_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    season_name = Column(String, nullable=False)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    status = Column(String, default="active")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (Index("idx_teams_lookup", "provider", "canonical_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String, nullable=False)
    country = Column(String)
    provider = Column(String)
    provider_team_id = Column(String)
    active = Column(Boolean, default=True)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        # Recherche de doublon par date et équipes (cf. _find_existing_match).
        Index("idx_matches_dedup", "provider", "match_date", "home_team_id", "away_team_id"),
        # Un identifiant fournisseur désigne un match et un seul.
        Index("uq_matches_provider_match", "provider", "provider_match_id", unique=True),
        # Sélection des matchs d'une compétition sur une période.
        Index("idx_matches_competition_date", "competition_id", "match_date"),
    )

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
    # Arbitre. Inutilisé en Phase 1 ; stocké parce que la donnée est gratuite,
    # présente dans le CSV, et perdue pour toujours si l'import la jette.
    referee = Column(String)
    source_created_at = Column(DateTime)
    source_updated_at = Column(DateTime)


class TeamMatchStats(Base):
    __tablename__ = "team_match_stats"
    __table_args__ = (Index("idx_tms_match_team", "match_id", "team_id"),)

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
    retrieved_at = Column(DateTime, default=maintenant_utc)
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
    retrieved_at = Column(DateTime, default=maintenant_utc)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (Index("idx_odds_match_id", "match_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    bookmaker = Column(String)
    market = Column(String)
    selection = Column(String)
    odds = Column(Float)
    captured_at = Column(DateTime, default=maintenant_utc)
    is_closing = Column(Boolean, default=False)
    source = Column(String)


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (
        # Une seule ligne de features par match et par équipe. L'idempotence du
        # pipeline reposait jusqu'ici sur un SELECT applicatif, sans filet.
        Index("uq_features_match_team", "match_id", "team_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    calculated_at = Column(DateTime, default=maintenant_utc)
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

    # Première mi-temps. Quinze des trente et une sélections d'un match y
    # portent, et rien ne la décrivait : le moteur prédisait la mi-temps sans
    # rien savoir du comportement des équipes en première période. `HTHG` et
    # `HTAG` étaient en base depuis le premier import ; seul le calcul dérivé
    # manquait. Voir `features/half_time.py`.
    ht_home_win_rate = Column(Float)
    ht_away_win_rate = Column(Float)
    ht_draw_rate = Column(Float)
    ht_home_goals_avg = Column(Float)
    ht_away_goals_avg = Column(Float)
    ht_total_goals_avg = Column(Float)
    ht_over_05_rate = Column(Float)
    ht_over_15_rate = Column(Float)
    ht_over_25_rate = Column(Float)
    ht_over_35_rate = Column(Float)

    # Encombrement du calendrier. Les jours de repos disent quand l'équipe a
    # joué pour la dernière fois, pas la charge accumulée.
    rest_days_diff = Column(Integer)
    matches_last_7_days = Column(Integer)
    matches_last_14_days = Column(Integer)

    # Solidité et stérilité, les deux moitiés du BTTS. Calculées par `form.py`
    # depuis toujours, elles étaient jetées faute de colonne.
    clean_sheets_5 = Column(Integer)
    failed_to_score_5 = Column(Integer)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        # Clé logique de la prédiction : un match, une version de modèle, un
        # marché, une sélection. Deux exécutions doivent mettre à jour la même
        # ligne, jamais en créer une seconde.
        Index(
            "uq_predictions_logique",
            "match_id",
            "model_version",
            "market",
            "selection",
            unique=True,
        ),
        # Consultation des prédictions d'un match.
        Index("idx_predictions_match", "match_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    model_version = Column(String)
    generated_at = Column(DateTime, default=maintenant_utc)
    # Date de coupure des données ayant servi à la prédiction, et versions des
    # sources consultées. Exigées par PROJECT_SPEC.md : sans elles, une
    # prédiction datée ne peut pas être rejouée ni auditée.
    data_cutoff_at = Column(DateTime)
    source_versions = Column(String)
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
    __table_args__ = (
        # Un résultat réglé par match, marché et sélection.
        Index("uq_actual_results_logique", "match_id", "market", "selection", unique=True),
    )

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
