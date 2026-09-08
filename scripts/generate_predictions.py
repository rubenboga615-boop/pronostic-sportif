#!/usr/bin/env python3
"""Générer les prédictions, un championnat à la fois.

Pendant exact de `train_models.py` : celui-ci entraîne **un modèle par
compétition** et l'enregistre sous ``{version}-comp{competition_id}``, ce
script recharge chaque modèle et ne lui soumet que les matchs de son propre
championnat.

Le faire dans l'autre sens ne lève aucune erreur, et c'est bien le danger. Les
forces d'équipes d'un Dixon-Coles n'ont de sens qu'à l'intérieur du
championnat sur lequel elles ont été ajustées ; une équipe inconnue fait
basculer le moteur sur son repli de Poisson, en silence. C'est ce qui s'est
produit le 08/09/2026 : 1 372 matchs de quatre championnats prédits par le
modèle de Premier League, et un backtest tous championnats confondus qui ne
voulait rien dire.

Deux garde-fous en découlent :

- la version exacte ``{version}-comp{id}`` doit exister au registre, sinon la
  compétition est **sautée avec une erreur** — jamais rabattue sur un autre
  modèle ;
- le modèle est chargé ici et passé au pipeline, pour court-circuiter le repli
  silencieux de ``charger_modele``.

Les modèles de mi-temps sont chargés de la même façon : le pipeline ne les
charge pas de lui-même, et sans eux les marchés de première période ne sont
pas produits du tout.

Usage :
    python scripts/generate_predictions.py --version dc-final
    python scripts/generate_predictions.py --version dc-final --competition 1
    python scripts/generate_predictions.py --version dc-final \
        --reference-date 2024-06-30 --cotes-de-cloture
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from sqlalchemy import text

REQUETE_COMPETITIONS = text(
    "SELECT id, name FROM competitions WHERE id IN "
    "(SELECT DISTINCT competition_id FROM matches WHERE competition_id IS NOT NULL) "
    "ORDER BY id"
)


def competitions_en_base(engine) -> list[tuple[int, str]]:
    """Compétitions ayant au moins un match, triées par identifiant."""
    with engine.connect() as connexion:
        return [(int(ligne[0]), ligne[1]) for ligne in connexion.execute(REQUETE_COMPETITIONS)]


def charger_couple_de_modeles(version: str, registre) -> tuple[Any, Any]:
    """Charger le Dixon-Coles et ses modèles de mi-temps, à cette version exacte.

    Retourne ``(None, None)`` si le modèle principal n'est pas enregistré :
    l'appelant doit alors sauter la compétition. Aucune version approchante
    n'est acceptée — c'est tout l'objet de ce script.
    """
    from models.dixon_coles import DixonColesModel
    from models.first_half import ModelesDeMiTemps

    parametres = registre.load("dixon_coles", version)
    if parametres is None:
        return None, None

    mi_temps = registre.load("dixon_coles_mi_temps", version)
    return (
        DixonColesModel.from_dict(parametres),
        ModelesDeMiTemps.from_dict(mi_temps) if mi_temps is not None else None,
    )


def predire(
    version: str,
    reference_date: datetime,
    competitions: list[int] | None = None,
    engine=None,
    registry_dir: str | None = None,
    valoriser: bool = True,
    cotes_de_cloture: bool = False,
    calibrer: bool = True,
) -> dict[int, dict[str, Any]]:
    """Lancer le pipeline une fois par compétition, avec le modèle qui lui va.

    Args:
        version: racine de version, sans le suffixe ``-comp{id}``.
        reference_date: date de coupure ; seuls les matchs strictement
            postérieurs sont prédits. Jamais inférée.
        competitions: identifiants à traiter ; par défaut, toutes celles qui
            ont des matchs en base.
        engine: moteur SQLAlchemy ; par défaut celui de l'application.
        registry_dir: répertoire du registre de modèles.
        valoriser: confronter les prédictions aux cotes du marché.
        cotes_de_cloture: utiliser les cotes de clôture (backtest seulement).
        calibrer: appliquer les calibrateurs enregistrés pour cette version.

    Returns:
        Rapport du pipeline, par identifiant de compétition. Une compétition
        sautée est absente du rapport.
    """
    from models.model_registry import ModelRegistry
    from pipelines.prediction_pipeline import run_prediction_pipeline

    if engine is None:
        from app.database import engine as moteur_par_defaut

        engine = moteur_par_defaut

    registre = ModelRegistry(registry_dir) if registry_dir else ModelRegistry()

    connues = competitions_en_base(engine)
    noms = dict(connues)
    if competitions is None:
        cibles = [identifiant for identifiant, _ in connues]
    else:
        cibles = list(competitions)

    rapports: dict[int, dict[str, Any]] = {}
    for competition_id in cibles:
        version_competition = f"{version}-comp{competition_id}"
        nom = noms.get(competition_id, "compétition inconnue")
        logger.info(f"=== {nom} (id {competition_id}) — {version_competition} ===")

        modele, mi_temps = charger_couple_de_modeles(version_competition, registre)
        if modele is None:
            logger.error(
                f"  Aucun modèle {version_competition!r} au registre : compétition "
                "sautée. La prédire avec le modèle d'un autre championnat "
                "produirait des probabilités de repli sans le signaler."
            )
            continue
        if mi_temps is None:
            logger.warning(
                f"  Pas de modèles de mi-temps pour {version_competition!r} : "
                "les marchés de première période ne seront pas produits."
            )

        rapports[competition_id] = run_prediction_pipeline(
            engine=engine,
            model_version=version_competition,
            reference_date=reference_date,
            model=modele,
            half_models=mi_temps,
            valoriser=valoriser,
            cotes_de_cloture=cotes_de_cloture,
            calibrer=calibrer,
            competition_id=competition_id,
        )

    return rapports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Générer les prédictions, un modèle par championnat"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Racine de version du modèle, sans le suffixe -comp{id} (exemple : dc-final)",
    )
    parser.add_argument(
        "--reference-date",
        default=None,
        help="Date de coupure AAAA-MM-JJ ; seuls les matchs postérieurs sont "
        "prédits (défaut : maintenant)",
    )
    parser.add_argument(
        "--competition",
        type=int,
        action="append",
        dest="competitions",
        help="Identifiant de compétition à traiter ; répétable "
        "(défaut : toutes celles présentes en base)",
    )
    parser.add_argument(
        "--no-valoriser",
        action="store_true",
        help="Ne pas confronter les prédictions aux cotes du marché",
    )
    parser.add_argument(
        "--cotes-de-cloture",
        action="store_true",
        help="Valoriser sur les cotes de clôture — backtest uniquement, elles "
        "ne sont pas connues au moment de prédire",
    )
    parser.add_argument(
        "--no-calibrer",
        action="store_true",
        help="Utiliser les probabilités brutes, sans les calibrateurs enregistrés",
    )
    args = parser.parse_args()

    if args.reference_date is None:
        reference_date = datetime.now()
    else:
        reference_date = datetime.fromisoformat(args.reference_date)

    logger.info("=== Génération de prédictions ===")
    logger.info(f"  date de coupure : {reference_date.isoformat()}")

    rapports = predire(
        version=args.version,
        reference_date=reference_date,
        competitions=args.competitions,
        valoriser=not args.no_valoriser,
        cotes_de_cloture=args.cotes_de_cloture,
        calibrer=not args.no_calibrer,
    )

    if not rapports:
        logger.warning("Aucune compétition prédite.")
        return

    total = 0
    for competition_id, rapport in rapports.items():
        total += rapport["predictions_created_or_updated"]
        logger.info(
            f"  compétition {competition_id} : "
            f"{rapport['predictions_created_or_updated']} prédictions, "
            f"{len(rapport['succeeded'])} matchs réussis, "
            f"{len(rapport['failed'])} échoués"
        )
    logger.info(f"=== {total} prédictions sur {len(rapports)} championnats ===")


if __name__ == "__main__":
    main()
