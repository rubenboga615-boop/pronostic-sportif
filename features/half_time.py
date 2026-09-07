"""Variables de première mi-temps.

Quinze des trente et une sélections produites par match portent sur la première
période — 1N2, double chance, over/under de mi-temps, mi-temps la plus
prolifique. Aucune variable ne la décrivait : le moteur prédisait la mi-temps
sans rien savoir du comportement des équipes en première période.

C'est l'explication la plus probable de l'écart mesuré entre le 1N2 de mi-temps
(0,609 d'AUC) et celui du match entier (0,693). Certaines équipes démarrent
lentement et rattrapent après la pause, d'autres font l'inverse ; un modèle
ajusté sur les seuls scores de mi-temps ne peut pas le distinguer d'un simple
bruit.

Les données étaient en base depuis le premier import : `HTHG` et `HTAG` sont
lues par le parseur Football-Data et écrites dans `matches`. Seul le calcul
dérivé manquait.

Deux règles héritées du reste du projet s'appliquent ici :

- **anti-fuite** — seuls les matchs strictement antérieurs à la date cible
  entrent dans le calcul, et la fenêtre est bornée à la saison en cours ;
- **une donnée absente vaut ``None``** — jamais ``0``, jamais une valeur
  plausible. Un match sans score de mi-temps est retiré du dénominateur, il
  n'est pas compté comme un 0-0.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Fenêtre par défaut. Dix matchs, comme la forme longue : assez pour qu'un taux
# ait un sens, assez court pour rester une mesure de la saison en cours.
FENETRE = 10

# En deçà, un taux n'est pas une information mais un artefact d'échantillon :
# sur deux matchs, un taux ne peut valoir que 0, 0,5 ou 1.
MINIMUM_OBSERVATIONS = 3

LIGNES_MI_TEMPS = (0.5, 1.5, 2.5, 3.5)


def _vide() -> dict[str, Any]:
    """Toutes les clés à ``None`` — la forme retournée quand rien n'est calculable."""
    base: dict[str, Any] = {
        "ht_home_win_rate": None,
        "ht_away_win_rate": None,
        "ht_draw_rate": None,
        "ht_home_goals_avg": None,
        "ht_away_goals_avg": None,
        "ht_total_goals_avg": None,
    }
    for ligne in LIGNES_MI_TEMPS:
        base[_cle_ligne(ligne)] = None
    return base


def _cle_ligne(ligne: float) -> str:
    """``0.5`` -> ``ht_over_05_rate``, ``2.5`` -> ``ht_over_25_rate``."""
    return f"ht_over_{str(ligne).replace('.', '')}_rate"


def calculate_half_time_features(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    season_id: Any = None,
    window: int = FENETRE,
) -> dict[str, Any]:
    """Décrire le comportement d'une équipe en première mi-temps.

    Args:
        matches_df: historique disponible. Doit porter ``home_team_id``,
            ``away_team_id``, ``match_date``, ``home_ht_goals`` et
            ``away_ht_goals``.
        team_id: équipe décrite.
        match_date: date du match à prédire. Borne stricte : rien à cette date
            ou après n'entre dans le calcul.
        season_id: saison du match. Fournie, elle borne la fenêtre — un taux
            calculé à cheval sur la trêve estivale décrit un effectif qui
            n'existe plus.
        window: nombre de matchs récents retenus.

    Returns:
        Les dix variables, chacune à ``None`` faute d'observations suffisantes.

    ⚠️ Anti-fuite : seuls les matchs AVANT ``match_date`` sont utilisés.
    """
    resultat = _vide()
    if matches_df is None or matches_df.empty:
        return resultat

    colonnes = set(matches_df.columns)
    if not {"home_ht_goals", "away_ht_goals"} <= colonnes:
        return resultat

    joues = matches_df[
        ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
        & (matches_df["match_date"] < match_date)
    ]
    if season_id is not None and "season_id" in colonnes:
        joues = joues[joues["season_id"] == season_id]

    joues = joues.sort_values("match_date").tail(window)
    if joues.empty:
        return resultat

    # Un match sans score de mi-temps ne dit rien : il sort du dénominateur.
    domicile: list[tuple[int, int]] = []  # (buts de l'équipe, buts adverses)
    exterieur: list[tuple[int, int]] = []

    for _, match in joues.iterrows():
        hg, ag = match["home_ht_goals"], match["away_ht_goals"]
        if pd.isna(hg) or pd.isna(ag):
            continue
        hg, ag = int(hg), int(ag)
        if match["home_team_id"] == team_id:
            domicile.append((hg, ag))
        else:
            exterieur.append((ag, hg))

    tous = domicile + exterieur
    if len(tous) < MINIMUM_OBSERVATIONS:
        return resultat

    # Taux de domination, séparés par lieu : une équipe qui mène souvent à la
    # pause chez elle et jamais au dehors n'est pas la même selon le match.
    resultat["ht_home_win_rate"] = _taux_de_tete(domicile)
    resultat["ht_away_win_rate"] = _taux_de_tete(exterieur)
    resultat["ht_draw_rate"] = sum(1 for pour, contre in tous if pour == contre) / len(tous)

    resultat["ht_home_goals_avg"] = _moyenne_marquee(domicile)
    resultat["ht_away_goals_avg"] = _moyenne_marquee(exterieur)
    resultat["ht_total_goals_avg"] = sum(pour + contre for pour, contre in tous) / len(tous)

    for ligne in LIGNES_MI_TEMPS:
        depasses = sum(1 for pour, contre in tous if pour + contre > ligne)
        resultat[_cle_ligne(ligne)] = depasses / len(tous)

    return resultat


def _taux_de_tete(matchs: list[tuple[int, int]]) -> float | None:
    """Part des matchs où l'équipe mène à la pause, ou ``None`` si trop peu."""
    if len(matchs) < MINIMUM_OBSERVATIONS:
        return None
    return sum(1 for pour, contre in matchs if pour > contre) / len(matchs)


def _moyenne_marquee(matchs: list[tuple[int, int]]) -> float | None:
    """Buts marqués en première période, en moyenne, ou ``None`` si trop peu."""
    if len(matchs) < MINIMUM_OBSERVATIONS:
        return None
    return sum(pour for pour, _ in matchs) / len(matchs)
