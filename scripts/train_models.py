#!/usr/bin/env python3
"""Entraîner les modèles de prédiction et les enregistrer.

Découpage chronologique conforme à `PROJECT_SPEC.md` : jamais de tirage
aléatoire. Le modèle apprend sur le passé, se règle sur une saison de
validation, et n'est jugé que sur des saisons qu'il n'a jamais vues.

Usage :
    python scripts/train_models.py
    python scripts/train_models.py --train-end 2022-06-30 --val-end 2023-06-30
    python scripts/train_models.py --version dixon-coles-2026-09
    python scripts/train_models.py --dry-run
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger

from app.database import SessionLocal
from models.dixon_coles import fit_dixon_coles
from models.first_half import fit_half_models
from models.model_registry import ModelRegistry

REQUETE = """
    SELECT id, competition_id, season_id, match_date,
           home_team_id, away_team_id, home_goals, away_goals,
           home_ht_goals, away_ht_goals
      FROM matches
     WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
     ORDER BY match_date, id
"""


def charger_matchs() -> pd.DataFrame:
    """Charger les matchs joués depuis la base."""
    session = SessionLocal()
    try:
        df = pd.read_sql_query(REQUETE, session.get_bind())
    finally:
        session.close()
    df["match_date"] = pd.to_datetime(df["match_date"])
    return df


def log_vraisemblance_moyenne(modele, matchs: pd.DataFrame) -> float:
    """Log-vraisemblance moyenne par match, sur un jeu non vu à l'entraînement.

    Comparable entre modèles et entre jeux de tailles différentes, à la
    différence de la log-vraisemblance totale.
    """
    if matchs.empty:
        return float("nan")

    total = 0.0
    for _, match in matchs.iterrows():
        matrice = modele.score_matrix(match["home_team_id"], match["away_team_id"], max_goals=10)
        hg = int(match["home_goals"])
        ag = int(match["away_goals"])
        if hg < matrice.shape[0] and ag < matrice.shape[1]:
            total += float(np.log(max(matrice[hg][ag], 1e-12)))
        else:
            total += float(np.log(1e-12))
    return total / len(matchs)


def entrainer(
    train_end: str,
    val_end: str,
    version: str,
    xi: float,
    dry_run: bool,
) -> dict:
    """Entraîner un modèle par compétition et l'enregistrer."""
    matchs = charger_matchs()
    if matchs.empty:
        logger.error("Aucun match joué en base : rien à entraîner.")
        return {}

    train = matchs[matchs["match_date"] <= train_end]
    validation = matchs[(matchs["match_date"] > train_end) & (matchs["match_date"] <= val_end)]
    logger.info(
        f"Découpage chronologique : {len(train)} matchs d'entraînement "
        f"(jusqu'au {train_end}), {len(validation)} de validation "
        f"(jusqu'au {val_end}), {len(matchs) - len(train) - len(validation)} réservés au test"
    )
    if train.empty:
        logger.error(
            f"Aucun match avant le {train_end}. La base ne couvre que "
            f"{matchs['match_date'].min().date()} → {matchs['match_date'].max().date()}."
        )
        return {}

    registre = ModelRegistry()
    resultats: dict = {}

    for competition_id, groupe in train.groupby("competition_id"):
        try:
            modele = fit_dixon_coles(
                groupe,
                xi=xi,
                reference_date=groupe["match_date"].max(),
                competition_id=competition_id,
            )
        except ValueError as erreur:
            logger.warning(f"Compétition {competition_id} non entraînée : {erreur}")
            continue

        val_competition = validation[validation["competition_id"] == competition_id]
        metriques = {
            "n_train": modele.n_matches,
            "n_validation": int(len(val_competition)),
            "log_vraisemblance_train": modele.log_likelihood,
            "log_vraisemblance_moyenne_validation": log_vraisemblance_moyenne(
                modele, val_competition
            ),
            "avantage_terrain": modele.home_advantage,
            "rho": modele.rho,
            "converge": modele.converged,
        }
        logger.info(
            f"Compétition {competition_id} : "
            f"log-vraisemblance moyenne en validation = "
            f"{metriques['log_vraisemblance_moyenne_validation']:.4f}"
        )

        version_competition = f"{version}-comp{competition_id}"
        if not dry_run:
            registre.register(
                "dixon_coles",
                version_competition,
                metrics=metriques,
                payload=modele.to_dict(),
            )

        # Modèles de mi-temps : sans eux, les marchés de première période et la
        # mi-temps la plus prolifique ne sont pas produits du tout — plutôt que
        # d'être devinés depuis une répartition moyenne.
        try:
            mi_temps = fit_half_models(
                groupe,
                xi=xi,
                reference_date=groupe["match_date"].max(),
                competition_id=competition_id,
            )
        except ValueError as erreur:
            logger.warning(f"Mi-temps non entraînées pour {competition_id} : {erreur}")
        else:
            metriques["mi_temps"] = {
                "avantage_terrain_1re": mi_temps.premiere.home_advantage,
                "avantage_terrain_2nde": mi_temps.seconde.home_advantage,
                "n_train": mi_temps.premiere.n_matches,
            }
            if not dry_run:
                registre.register(
                    "dixon_coles_mi_temps",
                    version_competition,
                    metrics=metriques["mi_temps"],
                    payload=mi_temps.to_dict(),
                )

        resultats[competition_id] = metriques

    return resultats


def main() -> None:
    parser = argparse.ArgumentParser(description="Entraîner les modèles de pronostic")
    parser.add_argument(
        "--train-end",
        default="2022-06-30",
        help="Dernière date incluse dans l'entraînement (défaut : 2022-06-30)",
    )
    parser.add_argument(
        "--val-end",
        default="2023-06-30",
        help="Dernière date incluse dans la validation (défaut : 2023-06-30)",
    )
    parser.add_argument(
        "--version",
        default=f"dixon-coles-{datetime.now(UTC).strftime('%Y%m%d')}",
        help="Identifiant de version du modèle",
    )
    parser.add_argument(
        "--xi",
        type=float,
        default=0.0018,
        help="Décroissance temporelle par jour ; 0 désactive la pondération",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Entraîner et évaluer sans rien enregistrer",
    )
    args = parser.parse_args()

    logger.info("=== Entraînement des modèles ===")
    resultats = entrainer(args.train_end, args.val_end, args.version, args.xi, args.dry_run)

    if not resultats:
        logger.warning("Aucun modèle entraîné.")
        return

    logger.info("=== Terminé ===")
    for competition_id, metriques in resultats.items():
        logger.info(
            f"  compétition {competition_id} : {metriques['n_train']} matchs, "
            f"rho={metriques['rho']:+.3f}, "
            f"avantage terrain={metriques['avantage_terrain']:+.3f}"
        )
    if args.dry_run:
        logger.info("  (--dry-run : rien n'a été enregistré)")


if __name__ == "__main__":
    main()
