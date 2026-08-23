"""Pipeline de calcul des features."""

from typing import Any

import pandas as pd
from loguru import logger

from app.models import Feature
from features.elo import DEFAULT_ELO, update_elo
from features.form import calculate_form_features
from features.home_away import calculate_home_away_features
from features.mapping import map_features_to_columns
from features.odds_movement import calculate_odds_movement
from features.rest_days import calculate_rest_features
from features.shots import calculate_shots_features
from features.standings import calculate_standings, get_team_position


def run_feature_pipeline() -> None:
    """Exécuter le pipeline de calcul des features.
    
    Étapes :
    1. Calculer les features de forme
    2. Calculer les features domicile/extérieur
    3. Calculer les features xG
    4. Calculer les features de tirs
    5. Calculer le classement
    6. Calculer les ratings Elo
    7. Calculer les jours de repos
    8. Calculer l'impact des blessures
    9. Calculer le mouvement des cotes
    """
    logger.info("=== Début du pipeline de features ===")
    # TODO: implémenter chaque étape
    logger.info("=== Pipeline de features terminé ===")


def compute_match_features(
    match: pd.Series,
    prior_matches_df: pd.DataFrame,
    odds_df: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Calculer en mémoire les features d'un match pour les deux équipes.

    Retourne deux dictionnaires alignés sur les colonnes du modèle ``Feature`` :
    ``{"home": {...}, "away": {...}}``, via ``map_features_to_columns`` avec un
    ``side`` explicite. Aucune écriture en base, aucun ``session``.

    Règles validées :
    - anti-fuite : seuls les matchs antérieurs à ``match_date`` sont utilisés ;
    - ``rest_days`` et ``elo_rating`` sont choisis selon le côté ;
    - ``odds_movement`` (match-level) est dupliqué sur les deux lignes ;
    - ``goal_difference`` n'est fourni que s'il est disponible avant le match ;
    - ``opponent_strength``, ``xg_*`` et ``injury_impact`` restent ``None``.
    """
    match_date = pd.Timestamp(match["match_date"])
    home_id = int(match["home_team_id"])
    away_id = int(match["away_team_id"])
    match_id = int(match["id"])
    competition_id = match.get("competition_id")

    # Anti-fuite : uniquement les matchs strictement antérieurs à la cible.
    prior = prior_matches_df[prior_matches_df["match_date"] < match_date]

    # Grandeurs partagées, calculées une seule fois.
    odds_movement = calculate_odds_movement(odds_df, match_id, market="1N2")[
        "odds_movement"
    ]
    rest = calculate_rest_features(prior, home_id, away_id, match_date)
    standings = calculate_standings(prior, match_date, competition_id=competition_id)
    elo_home = _compute_elo_before(prior, home_id)
    elo_away = _compute_elo_before(prior, away_id)

    result: dict[str, dict[str, Any]] = {}

    for side, team_id in (("home", home_id), ("away", away_id)):
        raw = {
            # match-level, dupliqué volontairement sur les deux lignes.
            "odds_movement": odds_movement,
            # côté-dépendant.
            "home_rest_days": rest["home_rest_days"],
            "away_rest_days": rest["away_rest_days"],
            "rest_days_difference": rest["rest_days_difference"],
            "home_elo": elo_home,
            "away_elo": elo_away,
            # par équipe.
            **calculate_form_features(prior, team_id, match_date, windows=[5, 10]),
            # NB : calculate_goals_features est volontairement écarté : ses
            # moyennes (fenêtre 10) écraseraient goals_for_avg_5/goals_against_avg_5
            # produites par calculate_form_features (fenêtre 5).
            # calculate_home_away_features : ses sorties (home/away_goals_for/against_avg)
            # sont actuellement calculées mais NON persistées (clés dans UNMAPPED_KEYS,
            # sans colonne Feature dédiée). Conservé tel quel par décision.
            **calculate_home_away_features(prior, team_id, match_date, window=10),
            **calculate_shots_features(prior, team_id, match_date, window=5),
            "league_position": get_team_position(standings, team_id),
            "goal_difference": _goal_difference(standings, team_id),
        }
        result[side] = map_features_to_columns(raw, side=side)

    return result


def _compute_elo_before(prior_df: pd.DataFrame, team_id: int) -> float:
    """Elo pré-match d'une équipe, calculé sur les seuls matchs antérieurs.

    Rejoue la boucle Elo chronologiquement ; les matchs sans buts renseignés sont
    ignorés. Retourne l'Elo courant (pré-match) de ``team_id``, ou ``DEFAULT_ELO``
    si aucun historique.
    """
    team_ids = set(prior_df["home_team_id"].dropna()) | set(
        prior_df["away_team_id"].dropna()
    )
    ratings: dict[int, float] = {int(tid): DEFAULT_ELO for tid in team_ids}
    ratings.setdefault(team_id, DEFAULT_ELO)

    for _, m in prior_df.sort_values("match_date").iterrows():
        hg = m.get("home_goals")
        ag = m.get("away_goals")
        if pd.isna(hg) or pd.isna(ag):
            continue
        hid = int(m["home_team_id"])
        aid = int(m["away_team_id"])
        he = ratings.get(hid, DEFAULT_ELO)
        ae = ratings.get(aid, DEFAULT_ELO)
        hg, ag = int(hg), int(ag)
        if hg > ag:
            nh, na = update_elo(he, ae)
        elif hg < ag:
            na, nh = update_elo(ae, he)
        else:
            nh, na = update_elo(he, ae, draw=True)
        ratings[hid] = nh
        ratings[aid] = na

    return ratings.get(team_id, DEFAULT_ELO)


def _goal_difference(standings: pd.DataFrame, team_id: int) -> int | None:
    """Différence de buts (gf - ga) pré-match, ou ``None`` si indisponible."""
    if standings is None or standings.empty or team_id not in standings.index:
        return None
    gf = standings.loc[team_id, "gf"]
    ga = standings.loc[team_id, "ga"]
    if pd.isna(gf) or pd.isna(ga):
        return None
    return int(gf) - int(ga)


def _upsert_feature(
    session,
    match_id: int,
    team_id: int,
    cols: dict[str, Any],
) -> Feature:
    """Insérer ou mettre à jour la ligne de features d'un match/équipe.

    Cherche la ``Feature`` existante par ``(match_id, team_id)``. Si elle existe,
    met à jour les colonnes présentes dans ``cols``. Sinon, crée une nouvelle
    ligne. Ne crée jamais de doublon.
    """
    feature = (
        session.query(Feature)
        .filter_by(match_id=match_id, team_id=team_id)
        .first()
    )
    if feature is None:
        feature = Feature(match_id=match_id, team_id=team_id, **cols)
        session.add(feature)
    else:
        for column, value in cols.items():
            setattr(feature, column, value)
    return feature


def persist_match_features(
    session,
    match: pd.Series,
    cols_home: dict[str, Any],
    cols_away: dict[str, Any],
) -> None:
    """Persister les deux lignes de features d'un match (domicile + extérieur).

    N'appelle pas ``session.commit()`` : le commit est laissé à l'appelant.
    """
    match_id = int(match["id"])
    _upsert_feature(session, match_id, int(match["home_team_id"]), cols_home)
    _upsert_feature(session, match_id, int(match["away_team_id"]), cols_away)


if __name__ == "__main__":
    run_feature_pipeline()
