#!/usr/bin/env python3
"""Mesurer le backtest sur plusieurs championnats à la fois.

`charger_evaluation` ne charge qu'une version de modèle. Depuis que chaque
championnat a la sienne — `{version}-comp{id}`, voir `train_models.py` et
`generate_predictions.py` — mesurer les cinq demande de réunir cinq jeux de
prédictions avant de les évaluer ensemble. C'est tout ce que fait ce script,
et il ne recalcule rien : les probabilités, les prix et les edges sont lus tels
qu'ils ont été écrits.

Le jeu de test par défaut est celui du protocole D-02 : **2024/25 et 2025/26**.
La saison de validation 2023/24 en est exclue, et doit le rester — une version
de modèle porte aussi les prédictions qui ont servi à ajuster son calibrateur,
et les agréger au jeu de test gonfle le résultat sans qu'aucune erreur ne soit
levée. C'est un défaut qui s'est déjà produit dans ce projet.

Usage :
    python scripts/mesurer_backtest.py --version dc-final
    python scripts/mesurer_backtest.py --version dc-final --competition 1
    python scripts/mesurer_backtest.py --version dc-final --saison 2526
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

# Jeu de test du protocole D-02. La validation (2023/24) n'y figure pas.
SAISONS_DE_TEST = ["2425", "2526"]


def charger_les_championnats(
    session,
    version: str,
    competitions: list[int],
    saisons: list[str],
) -> pd.DataFrame:
    """Réunir les prédictions réglées des versions ``{version}-comp{id}``.

    Une compétition sans aucune prédiction est signalée et ignorée : mieux vaut
    mesurer les quatre autres que ne rien rendre.
    """
    from evaluation.backtest import charger_evaluation

    morceaux = []
    for competition_id in competitions:
        version_competition = f"{version}-comp{competition_id}"
        df = charger_evaluation(session, model_version=version_competition, saisons=saisons)
        if df.empty:
            logger.warning(
                f"  compétition {competition_id} : aucune prédiction réglée pour "
                f"{version_competition!r} — ignorée"
            )
            continue
        logger.info(
            f"  compétition {competition_id} : {df['match_id'].nunique()} matchs, "
            f"{len(df)} sélections ({version_competition})"
        )
        morceaux.append(df)

    if not morceaux:
        return pd.DataFrame()
    return pd.concat(morceaux, ignore_index=True)


def intervalles_de_confiance(df: pd.DataFrame, rapport: dict[str, Any]) -> dict[str, Any]:
    """Encadrer les rendements mesurés, marché par marché et stratégie par stratégie.

    Un ROI ponctuel ne dit pas s'il est distinguable de zéro. C'est la seule
    chose qui permette d'écrire « démontré » plutôt que « constaté ».

    Les filtres reproduisent **exactement** ceux de `evaluation.backtest`, faute
    de quoi les bornes encadreraient d'autres paris que ceux dont le rendement
    est publié. `test_mesurer_backtest` compare les effectifs des deux côtés
    pour que toute divergence future casse un test plutôt que de passer.
    """
    from evaluation.backtest import COTE_MAXIMALE, COTE_MINIMALE
    from evaluation.incertitude import intervalle_de_confiance_roi

    pariables = df[df["offered_odds"].notna() & (df["offered_odds"] > 1.0)]

    resultats: dict[str, Any] = {"par_marche": {}, "par_championnat": {}, "strategies": {}}
    for marche, lot in pariables.groupby("market"):
        resultats["par_marche"][str(marche)] = intervalle_de_confiance_roi(
            lot["actual_outcome"], lot["offered_odds"]
        )

    # Un rendement d'ensemble peut masquer un championnat qui porte seul la
    # perte, ou un seul qui porte le gain. La ventilation le dit.
    for (competition_id, marche), lot in pariables.groupby(["competition_id", "market"]):
        resultats["par_championnat"].setdefault(str(int(competition_id)), {})[str(marche)] = (
            intervalle_de_confiance_roi(lot["actual_outcome"], lot["offered_odds"])
        )

    def par_edge(minimum: float) -> pd.DataFrame:
        return df[
            df["edge"].notna()
            & (df["edge"] >= minimum)
            & df["offered_odds"].notna()
            & (df["offered_odds"] >= COTE_MINIMALE)
            & (df["offered_odds"] <= COTE_MAXIMALE)
        ]

    un_n_deux = df[(df["market"] == "1N2") & df["offered_odds"].notna()]
    favoris = (
        un_n_deux.loc[un_n_deux.groupby("match_id")["offered_odds"].idxmin()]
        if not un_n_deux.empty
        else un_n_deux
    )

    for nom, lot in (
        ("edge_5pct", par_edge(0.05)),
        ("edge_2pct", par_edge(0.02)),
        ("favori_du_marche", favoris),
    ):
        resultats["strategies"][nom] = intervalle_de_confiance_roi(
            lot["actual_outcome"], lot["offered_odds"]
        )

    return resultats


def mesurer(
    version: str,
    competitions: list[int] | None = None,
    saisons: list[str] | None = None,
    engine=None,
    repertoire: str = "rapports",
) -> dict[str, Any]:
    """Charger, évaluer et écrire le rapport. Ne modifie jamais la base.

    Returns:
        Le rapport de :func:`run_backtest`, augmenté du périmètre mesuré.
    """
    from evaluation.backtest import run_backtest
    from scripts.generate_predictions import competitions_en_base

    if engine is None:
        from app.database import engine as moteur_par_defaut

        engine = moteur_par_defaut

    saisons = list(saisons) if saisons else list(SAISONS_DE_TEST)
    if competitions is None:
        competitions = [identifiant for identifiant, _ in competitions_en_base(engine)]

    from sqlalchemy.orm import Session

    logger.info(f"Saisons de test : {', '.join(saisons)}")
    with Session(engine) as session:
        df = charger_les_championnats(session, version, competitions, saisons)

    if df.empty:
        logger.error("Aucune prédiction réglée sur ce périmètre : rien à mesurer.")
        return {"erreur": "aucune prédiction réglée à évaluer"}

    rapport = run_backtest(df)
    rapport["intervalles"] = intervalles_de_confiance(df, rapport)
    rapport["perimetre"] = {
        "version": version,
        "saisons": saisons,
        "competitions": sorted(int(c) for c in df["competition_id"].unique()),
    }

    chemin = Path(repertoire)
    chemin.mkdir(parents=True, exist_ok=True)
    fichier = chemin / f"backtest_{version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    fichier.write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    logger.info(f"Rapport écrit : {fichier}")
    rapport["fichier"] = str(fichier)
    return rapport


def _roi(rendement: dict[str, Any] | None) -> str:
    """ROI d'un bloc ``rendement``. Déjà exprimé en pourcentage par le backtest."""
    if not rendement or rendement.get("roi_pct") is None:
        return "—"
    return f"{float(rendement['roi_pct']):+.2f} %"


def _paris(rendement: dict[str, Any] | None) -> int:
    return int((rendement or {}).get("paris") or 0)


def afficher(rapport: dict[str, Any]) -> None:
    """Résumé lisible du rapport, sans recalcul."""
    if "erreur" in rapport:
        logger.error(rapport["erreur"])
        return

    perimetre = rapport["perimetre"]
    logger.info(
        f"=== {rapport['n_matchs']} matchs, {rapport['n_selections']} sélections, "
        f"championnats {perimetre['competitions']} ==="
    )

    logger.info("Par marché :")
    for marche, metriques in sorted(rapport["par_marche"].items()):
        rendement = metriques.get("rendement")
        auc = metriques.get("auc")
        logger.info(
            f"  {marche:<22} n={metriques.get('n_selections', 0):>6}  "
            f"AUC={'—' if auc is None else format(float(auc), '.3f'):>5}  "
            f"paris={_paris(rendement):>6}  ROI={_roi(rendement):>8}"
        )

    logger.info("Stratégies de référence :")
    for nom, resultat in rapport["strategies"].items():
        rendement = resultat.get("rendement")
        logger.info(f"  {nom:<20} paris={_paris(rendement):>6}  ROI={_roi(rendement):>8}")

    intervalles = rapport.get("intervalles", {})
    if intervalles:
        logger.info("Intervalles de confiance à 95 % (bootstrap par pari) :")
        for origine in ("par_marche", "strategies"):
            for nom, bloc in sorted(intervalles.get(origine, {}).items()):
                if bloc.get("roi_pct") is None:
                    continue
                verdict = "signe établi" if bloc["significatif"] else "indistinguable de zéro"
                logger.info(
                    f"  {nom:<22} {bloc['paris']:>6} paris  "
                    f"{bloc['roi_pct']:+.2f} % "
                    f"[{bloc['borne_basse']:+.2f} ; {bloc['borne_haute']:+.2f}]  {verdict}"
                )

    logger.info("Par championnat et par marché, avec intervalle :")
    for competition_id, marches in sorted(intervalles.get("par_championnat", {}).items()):
        for marche, bloc in sorted(marches.items()):
            if bloc.get("roi_pct") is None:
                continue
            verdict = "signe établi" if bloc["significatif"] else "nul"
            logger.info(
                f"  comp {competition_id} {marche:<12} {bloc['paris']:>5} paris  "
                f"{bloc['roi_pct']:+.2f} % "
                f"[{bloc['borne_basse']:+.2f} ; {bloc['borne_haute']:+.2f}]  {verdict}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest multi-championnats")
    parser.add_argument(
        "--version",
        required=True,
        help="Racine de version, sans le suffixe -comp{id} (exemple : dc-final)",
    )
    parser.add_argument(
        "--competition",
        type=int,
        action="append",
        dest="competitions",
        help="Identifiant de compétition ; répétable (défaut : toutes)",
    )
    parser.add_argument(
        "--saison",
        action="append",
        dest="saisons",
        help=f"Saison à mesurer ; répétable (défaut : {' et '.join(SAISONS_DE_TEST)}, "
        "jeu de test du protocole D-02)",
    )
    args = parser.parse_args()

    logger.info("=== Backtest ===")
    afficher(
        mesurer(
            version=args.version,
            competitions=args.competitions,
            saisons=args.saisons,
        )
    )


if __name__ == "__main__":
    main()
