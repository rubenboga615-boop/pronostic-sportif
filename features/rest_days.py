"""Jours de repos et encombrement du calendrier.

Les jours de repos disent quand l'équipe a joué pour la dernière fois. Ils ne
disent rien de la charge accumulée : deux équipes peuvent arriver à trois jours
de repos, l'une après un match en trois semaines, l'autre après son quatrième en
quinze jours. Le nombre de matchs disputés sur les sept et quatorze derniers
jours complète donc la mesure.

C'est une information qui n'est pas dans les résultats passés — contrairement à
la forme, à l'Elo ou au classement, tous dérivés du même registre de buts.
"""

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


def calculate_congestion(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    season_id: int | None = None,
) -> dict:
    """Compter les matchs disputés sur les 7 et 14 derniers jours.

    Contrairement aux jours de repos, l'encombrement existe dès le premier match
    d'une saison : la réponse est alors ``0``, et c'est une information vraie,
    pas une valeur de remplacement. Il n'y a donc pas de ``None`` ici.

    ⚠️ Anti-fuite : la borne haute est stricte. Le match cible lui-même, et tout
    autre match du même jour, sont exclus.
    """
    fenetres = {"matches_last_7_days": 7, "matches_last_14_days": 14}
    if matches_df is None or matches_df.empty:
        return dict.fromkeys(fenetres, 0)

    joues = matches_df[
        ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
        & (matches_df["match_date"] < match_date)
    ]
    if season_id is not None and "season_id" in matches_df.columns:
        joues = joues[joues["season_id"] == season_id]

    return {
        cle: int((joues["match_date"] >= match_date - pd.Timedelta(days=jours)).sum())
        for cle, jours in fenetres.items()
    }


def calculate_congestion_features(
    matches_df: pd.DataFrame,
    home_team_id: int,
    away_team_id: int,
    match_date: pd.Timestamp,
    season_id: int | None = None,
) -> dict:
    """Encombrement des deux équipes, préfixé par côté."""
    features = {}
    for prefixe, team_id in (("home", home_team_id), ("away", away_team_id)):
        for cle, valeur in calculate_congestion(matches_df, team_id, match_date, season_id).items():
            features[f"{prefixe}_{cle}"] = valeur
    return features
