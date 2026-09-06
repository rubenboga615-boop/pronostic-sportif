"""Pipeline de calcul des features."""

from typing import Any

import pandas as pd
from loguru import logger

from app.database import SessionLocal
from app.models import Feature
from features.elo import DEFAULT_ELO, regress_towards_mean, update_elo
from features.form import calculate_form_features
from features.home_away import calculate_home_away_features
from features.mapping import map_features_to_columns
from features.odds_movement import calculate_odds_movement
from features.rest_days import calculate_rest_features
from features.shots import calculate_shots_features
from features.standings import calculate_standings, get_team_position


def run_feature_pipeline() -> dict[str, int]:
    """Calculer et persister les features de tous les matchs (idempotent).

    Charge les matchs (ordre chronologique ``match_date`` puis ``id``) et les
    cotes, calcule les features via :func:`compute_match_features` en ne
    fournissant que l'historique strictement antérieur (anti-fuite), puis
    persiste deux lignes par match via :func:`persist_match_features`.

    Transaction : un seul ``commit`` en fin de traitement ; ``rollback`` puis
    re-levée de l'exception en cas d'erreur ; ``close`` toujours en ``finally``.
    """
    logger.info("=== Début du pipeline de features ===")
    session = SessionLocal()
    try:
        matches_df = pd.read_sql_query(
            "SELECT id, competition_id, season_id, match_date, home_team_id, away_team_id, "
            "home_goals, away_goals, home_shots, away_shots, "
            "home_shots_on_target, away_shots_on_target "
            "FROM matches ORDER BY match_date, id",
            session.get_bind(),
        )
        odds_df = pd.read_sql_query(
            "SELECT match_id, market, selection, odds, captured_at, bookmaker, is_closing "
            "FROM odds_snapshots",
            session.get_bind(),
        )
        matches_df["match_date"] = pd.to_datetime(matches_df["match_date"])

        processed = 0
        for _, match in matches_df.iterrows():
            # Anti-fuite : uniquement l'historique strictement antérieur.
            prior = matches_df[matches_df["match_date"] < match["match_date"]]
            cols = compute_match_features(match, prior, odds_df)
            persist_match_features(session, match, cols["home"], cols["away"])
            processed += 1

        session.commit()
        logger.info(f"=== Pipeline terminé : {processed} matchs traités ===")
        return {"matches_processed": processed}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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
    - ``odds_movement`` est calculé par sélection (``home``/``away``) selon le côté,
      en n'observant que des cotes capturées avant le coup d'envoi ;
    - ``goal_difference`` n'est fourni que s'il est disponible avant le match ;
    - ``opponent_strength``, ``xg_*`` et ``injury_impact`` restent ``None``.
    """
    match_date = pd.Timestamp(match["match_date"])
    home_id = int(match["home_team_id"])
    away_id = int(match["away_team_id"])
    match_id = int(match["id"])
    competition_id = match.get("competition_id")
    season_id = match.get("season_id")
    if pd.isna(season_id):
        season_id = None

    # Anti-fuite : uniquement les matchs strictement antérieurs à la cible.
    prior = prior_matches_df[prior_matches_df["match_date"] < match_date]

    # Grandeurs partagées, calculées une seule fois.
    rest = calculate_rest_features(prior, home_id, away_id, match_date, season_id=season_id)
    standings = calculate_standings(
        prior, match_date, competition_id=competition_id, season_id=season_id
    )
    elo_home = _compute_elo_before(prior, home_id, season_id=season_id)
    elo_away = _compute_elo_before(prior, away_id, season_id=season_id)

    result: dict[str, dict[str, Any]] = {}

    for side, team_id in (("home", home_id), ("away", away_id)):
        # Sélection de cote selon le côté : home -> "home", away -> "away".
        # Date de coupure = coup d'envoi : aucune cote postérieure, et aucune
        # cote de clôture, ne peut entrer dans les features.
        odds_movement = calculate_odds_movement(
            odds_df, match_id, market="1N2", selection=side, cutoff=match_date
        )["odds_movement"]
        raw = {
            # par sélection (home -> "home", away -> "away").
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


def _compute_elo_before(
    prior_df: pd.DataFrame, team_id: int, season_id: int | None = None
) -> float:
    """Elo pré-match d'une équipe, calculé sur les seuls matchs antérieurs.

    Rejoue la boucle Elo chronologiquement ; les matchs sans buts renseignés sont
    ignorés. Le rating est conservé d'une saison à l'autre mais ramené vers la
    moyenne à chaque changement de saison (voir ``regress_towards_mean``), y
    compris pour la saison du match cible lorsque ``season_id`` est fourni.

    Retourne l'Elo pré-match de ``team_id``, ou ``DEFAULT_ELO`` si aucun
    historique.
    """
    team_ids = set(prior_df["home_team_id"].dropna()) | set(prior_df["away_team_id"].dropna())
    ratings: dict[int, float] = {int(tid): DEFAULT_ELO for tid in team_ids}
    ratings.setdefault(team_id, DEFAULT_ELO)
    last_season: dict[int, object] = {}

    for _, m in prior_df.sort_values("match_date").iterrows():
        hg = m.get("home_goals")
        ag = m.get("away_goals")
        if pd.isna(hg) or pd.isna(ag):
            continue
        hid = int(m["home_team_id"])
        aid = int(m["away_team_id"])
        season = m.get("season_id")
        for tid in (hid, aid):
            _apply_season_regression(ratings, last_season, tid, season)
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

    # Le match cible peut ouvrir une nouvelle saison pour cette équipe.
    if season_id is not None:
        _apply_season_regression(ratings, last_season, team_id, season_id)

    return ratings.get(team_id, DEFAULT_ELO)


def _apply_season_regression(
    ratings: dict[int, float],
    last_season: dict[int, object],
    team_id: int,
    season: object,
) -> None:
    """Ramener le rating vers la moyenne si l'équipe entre dans une saison neuve."""
    if season is None or (isinstance(season, float) and pd.isna(season)):
        return
    previous = last_season.get(team_id)
    if previous is not None and previous != season:
        ratings[team_id] = regress_towards_mean(ratings.get(team_id, DEFAULT_ELO))
    last_season[team_id] = season


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
    feature = session.query(Feature).filter_by(match_id=match_id, team_id=team_id).first()
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
