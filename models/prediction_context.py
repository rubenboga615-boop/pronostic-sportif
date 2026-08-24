"""Construction du contexte de prédiction anti-fuite d'un match cible.

Charge le match cible, ses deux lignes ``Feature`` (domicile et extérieur), puis
calcule la moyenne de buts de la ligue sur l'historique strictement antérieur à
la date du match (anti-fuite). Ne produit **aucune** écriture en base.
"""

from __future__ import annotations

from typing import Any

from app.models import Feature, Match
from models.market_assembly import build_match_markets, estimate_match_lambdas

DEFAULT_HOME_ADVANTAGE = 0.25


def build_prediction_context(session, target_match_id: int) -> dict[str, Any]:
    """Construire le contexte de prédiction d'un match cible.

    Retourne un dictionnaire contenant au minimum : ``target_match``,
    ``home_features``, ``away_features``, ``league_avg_goals``,
    ``home_advantage``, ``lambda_home`` et ``lambda_away``.
    """
    target_match, home_features, away_features, league_avg_goals = _load_context(
        session, target_match_id
    )
    home_advantage = DEFAULT_HOME_ADVANTAGE
    lambda_home, lambda_away = estimate_match_lambdas(
        home_features,
        away_features,
        league_avg_goals,
        home_advantage=home_advantage,
    )
    return {
        "target_match": target_match,
        "home_features": home_features,
        "away_features": away_features,
        "league_avg_goals": league_avg_goals,
        "home_advantage": home_advantage,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
    }


def build_match_predictions(
    session,
    target_match_id: int,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
) -> list[dict[str, Any]]:
    """Produire les 16 prédictions normalisées d'un match cible (sans écriture).

    Retourne la liste au format ``{"market", "selection", "probability",
    "fair_odds"}`` avec les identifiants publics, sans écrire en base.
    """
    _, home_features, away_features, league_avg_goals = _load_context(
        session, target_match_id
    )
    return build_match_markets(
        home_features,
        away_features,
        league_avg_goals,
        home_advantage=home_advantage,
    )


def _load_context(session, target_match_id: int):
    target_match = _get_match(session, target_match_id)
    home_features, away_features = _get_features(session, target_match_id, target_match)
    league_avg_goals = _compute_league_avg_goals(session, target_match)
    return target_match, home_features, away_features, league_avg_goals


def _get_match(session, target_match_id: int) -> Match:
    target_match = session.get(Match, target_match_id)
    if target_match is None:
        raise LookupError(f"Match {target_match_id} introuvable")
    if target_match.match_date is None:
        raise ValueError(f"Match {target_match_id} sans date")
    if target_match.home_team_id is None or target_match.away_team_id is None:
        raise ValueError(f"Match {target_match_id} sans équipe domicile/extérieure")
    return target_match


def _get_features(session, target_match_id: int, target_match: Match):
    rows = session.query(Feature).filter_by(match_id=target_match_id).all()
    home = next((f for f in rows if f.team_id == target_match.home_team_id), None)
    away = next((f for f in rows if f.team_id == target_match.away_team_id), None)
    if home is None:
        raise LookupError(f"Feature domicile manquante pour le match {target_match_id}")
    if away is None:
        raise LookupError(f"Feature extérieure manquante pour le match {target_match_id}")
    return _feature_to_dict(home), _feature_to_dict(away)


def _feature_to_dict(feature: Feature) -> dict[str, Any]:
    """Convertir une ``Feature`` en dict des colonnes utilisées par le modèle.

    Les valeurs ``None`` sont conservées telles quelles : le fallback neutre de
    ``market_assembly`` s'appliquera à la place.
    """
    return {
        "goals_for_avg_5": feature.goals_for_avg_5,
        "goals_against_avg_5": feature.goals_against_avg_5,
    }


def _compute_league_avg_goals(session, target_match: Match) -> float:
    """Moyenne de buts par équipe et par match, sur l'historique antérieur.

    Anti-fuite : seuls les matchs strictement antérieurs à ``match_date`` sont
    considérés (comparaison ``match_date < cible``). Les scores ``NULL`` sont
    ignorés. La moyenne est calculée **par compétition** (chaque championnat a
    son propre rythme de buts).
    """
    query = session.query(Match).filter(
        Match.match_date < target_match.match_date,
        Match.home_goals.isnot(None),
        Match.away_goals.isnot(None),
    )
    if target_match.competition_id is not None:
        query = query.filter(Match.competition_id == target_match.competition_id)

    rows = query.all()
    if not rows:
        raise ValueError(
            f"Aucun historique exploitable avant le match {target_match.id}"
        )

    total_goals = sum(m.home_goals + m.away_goals for m in rows)
    return total_goals / (2.0 * len(rows))
