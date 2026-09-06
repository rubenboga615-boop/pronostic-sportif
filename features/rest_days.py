"""Calcul des jours de repos entre les matchs."""

import pandas as pd


def calculate_rest_days(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    season_id: int | None = None,
) -> int | None:
    """Calculer les jours de repos d'une équipe avant un match.

    Fournir ``season_id`` restreint le calcul à la saison en cours. Sans cette
    borne, l'écart avec le dernier match de la saison précédente est compté
    comme du repos : la trêve estivale produit alors des valeurs de 90 jours et
    plus, qui ne mesurent aucune fraîcheur.

    Retourne ``None`` en première journée de saison : l'information n'existe
    pas, et une valeur plausible ne doit jamais lui être substituée.

    ⚠️ Anti-fuite : seuls les matchs AVANT match_date sont utilisés.
    """
    team_matches = matches_df[
        ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
        & (matches_df["match_date"] < match_date)
    ].sort_values("match_date")

    if season_id is not None and "season_id" in team_matches.columns:
        team_matches = team_matches[team_matches["season_id"] == season_id]

    if team_matches.empty:
        return None

    last_match_date = team_matches.iloc[-1]["match_date"]
    if pd.isna(last_match_date):
        return None

    rest = (match_date - last_match_date).days
    return max(rest, 0)


def calculate_rest_features(
    matches_df: pd.DataFrame,
    home_team_id: int,
    away_team_id: int,
    match_date: pd.Timestamp,
    season_id: int | None = None,
) -> dict:
    """Calculer les features de repos pour les deux équipes."""
    home_rest = calculate_rest_days(matches_df, home_team_id, match_date, season_id)
    away_rest = calculate_rest_days(matches_df, away_team_id, match_date, season_id)

    features = {
        "home_rest_days": home_rest,
        "away_rest_days": away_rest,
    }

    if home_rest is not None and away_rest is not None:
        features["rest_days_difference"] = home_rest - away_rest
    else:
        features["rest_days_difference"] = None

    return features
