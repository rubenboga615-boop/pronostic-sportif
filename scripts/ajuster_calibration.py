#!/usr/bin/env python3
"""Ajuster les calibrateurs d'un modèle sur une saison de validation.

Une probabilité calibrée tient sa promesse : ce qui est annoncé à 60 % se
produit six fois sur dix. Un modèle peut très bien classer correctement les
matchs et perdre de l'argent pour la seule raison qu'il est trop confiant — un
edge est un écart de probabilités, il n'a aucun sens si l'une des deux est
biaisée.

Mesuré le 08/09/2026 sur les données réelles : la calibration ramenait l'erreur
de 0,107 à 0,044 et récupérait dix points de ROI sur la sélection à 5 % du 1N2,
qui passait de −16,2 % à −6,1 %.

Règle non négociable
--------------------
Le calibrateur s'ajuste sur une saison que le modèle **n'a pas vue à
l'entraînement**, et jamais sur le jeu de test. L'ajuster sur les données qui
serviront à mesurer la performance reviendrait à s'auto-évaluer sur ses propres
réponses. Le script vérifie ce qu'il peut et refuse une saison vide, mais il ne
peut pas deviner sur quoi le modèle a été entraîné : c'est à l'appelant de
fournir une saison de validation légitime.

Usage :
    python scripts/ajuster_calibration.py --version dc-calib-comp1 --saison 2324
    python scripts/ajuster_calibration.py --version dc-calib-comp1 --saison 2324 \\
        --methode isotonic --simuler
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import text

from app.database import SessionLocal
from models.calibration import METHODES, ajuster_calibrateur
from models.calibration_appliquee import NOM_MODELE
from models.model_registry import ModelRegistry

# En dessous, un calibrateur apprendrait le bruit de quelques dizaines de
# matchs plutôt que le biais du modèle.
MINIMUM_OBSERVATIONS = 200

REQUETE = text("""
    SELECT p.market, p.probability, r.actual_outcome AS issue
      FROM predictions p
      JOIN matches m ON m.id = p.match_id
      JOIN seasons s ON s.id = m.season_id
      JOIN actual_results r
        ON r.match_id = p.match_id
       AND r.market = p.market
       AND r.selection = p.selection
     WHERE p.model_version = :version
       AND s.season_name = :saison
""")


def charger_observations(version: str, saison: str) -> pd.DataFrame:
    """Probabilités annoncées et issues observées, pour une saison."""
    session = SessionLocal()
    try:
        df = pd.read_sql_query(
            REQUETE, session.get_bind(), params={"version": version, "saison": saison}
        )
    finally:
        session.close()
    df["gagne"] = (df["issue"].astype(str).str.lower() == "won").astype(int)
    return df


def erreur_de_calibration(probabilites, issues, n_tranches: int = 10) -> float:
    """Écart moyen entre annoncé et observé, pondéré par les effectifs."""
    p = np.asarray(probabilites, dtype=float)
    y = np.asarray(issues, dtype=float)
    tranches = np.clip((p * n_tranches).astype(int), 0, n_tranches - 1)
    total, poids = 0.0, 0
    for tranche in range(n_tranches):
        masque = tranches == tranche
        effectif = int(masque.sum())
        if effectif >= 10:
            total += abs(p[masque].mean() - y[masque].mean()) * effectif
            poids += effectif
    return total / poids if poids else float("nan")


def ajuster(version: str, saison: str, methode: str, simuler: bool) -> dict:
    """Ajuster un calibrateur par marché et l'enregistrer."""
    df = charger_observations(version, saison)
    if df.empty:
        raise SystemExit(
            f"Aucune prédiction réglée pour {version!r} en {saison!r}.\n"
            f"Générez les prédictions et réglez les résultats de cette saison d'abord."
        )

    logger.info(f"{len(df)} observations sur {df['market'].nunique()} marchés")

    par_marche: dict[str, dict] = {}
    rapport: dict[str, dict] = {}
    for marche, lot in df.groupby("market"):
        if len(lot) < MINIMUM_OBSERVATIONS:
            logger.warning(
                f"  {marche} : {len(lot)} observations, moins que le minimum de "
                f"{MINIMUM_OBSERVATIONS} — ignoré"
            )
            continue
        if lot["gagne"].nunique() < 2:
            logger.warning(f"  {marche} : une seule issue observée — ignoré")
            continue

        calibrateur = ajuster_calibrateur(
            lot["gagne"].values, lot["probability"].values, methode=methode
        )
        avant = erreur_de_calibration(lot["probability"].values, lot["gagne"].values)
        apres = erreur_de_calibration(
            calibrateur.transform(lot["probability"].values), lot["gagne"].values
        )
        par_marche[str(marche)] = calibrateur.to_dict()
        rapport[str(marche)] = {
            "observations": int(len(lot)),
            "erreur_avant": round(float(avant), 4),
            "erreur_apres": round(float(apres), 4),
        }
        logger.info(f"  {marche:22} {len(lot):5d} obs — erreur {avant:.4f} -> {apres:.4f}")

    if not par_marche:
        raise SystemExit("Aucun marché n'a réuni assez d'observations.")

    if simuler:
        logger.info("--simuler : aucun calibrateur enregistré.")
        return rapport

    ModelRegistry().register(
        NOM_MODELE,
        version,
        metrics={"saison_de_calibration": saison, "methode": methode, **rapport},
        payload={"methode": methode, "saison": saison, "par_marche": par_marche},
    )
    logger.info(f"Calibrateurs enregistrés sous {NOM_MODELE} v{version}")
    logger.info("Le pipeline de prédiction les appliquera automatiquement.")
    return rapport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Version du modèle à calibrer")
    parser.add_argument(
        "--saison",
        required=True,
        help="Saison de validation (ex : 2324). Doit être absente de l'entraînement.",
    )
    parser.add_argument("--methode", choices=METHODES, default="platt")
    parser.add_argument("--simuler", action="store_true", help="Mesurer sans enregistrer")
    args = parser.parse_args()

    logger.info(f"Calibration {args.methode} de {args.version} sur {args.saison}")
    ajuster(args.version, args.saison, args.methode, args.simuler)


if __name__ == "__main__":
    main()
