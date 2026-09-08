"""Appliquer une calibration à un lot de prédictions, marché par marché.

`models/calibration.py` sait apprendre une transformation et l'appliquer à un
tableau de probabilités. Il manquait la marche d'après : appliquer cette
transformation à des prédictions structurées — un marché, une sélection, une
probabilité — sans casser ce qui les rend cohérentes.

Deux exigences s'imposent, et la seconde est facile à oublier.

**Un calibrateur par marché.** Les probabilités d'un 1N2 et celles d'un
Over/Under n'ont ni la même distribution, ni le même biais : mesuré le
08/09/2026, la calibration récupérait dix points de ROI sur le 1N2 et faisait
passer l'Over/Under d'un rendement négatif à un rendement positif — deux
corrections de nature différente. Un calibrateur unique les mélangerait.

**Renormaliser les groupes exclusifs.** La calibration déforme chaque
probabilité indépendamment ; les trois sélections d'un 1N2 cessent donc de
sommer à 1. Une probabilité qui ne somme pas fausse l'edge, la cote équitable,
et toute probabilité jointe calculée plus tard. Les groupes sont lus dans
:data:`models.market_assembly.GROUPES_EXCLUSIFS`, pour qu'une seule définition
fasse foi.

Les marchés sans partition — la double chance, dont deux sélections sur trois
gagnent à chaque match — sont calibrés sans renormalisation : il n'y a rien à y
normaliser.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from models.calibration import Calibrateur
from models.market_assembly import GROUPES_EXCLUSIFS

# En dessous, renormaliser amplifierait du bruit numérique plutôt que de
# corriger quoi que ce soit.
SOMME_MINIMALE = 1e-9


def _renormaliser(predictions: list[dict[str, Any]], marche: str) -> None:
    """Ramener chaque groupe exclusif du marché à une somme de 1, sur place."""
    for groupe in GROUPES_EXCLUSIFS.get(marche, ()):
        membres = [p for p in predictions if p.get("selection") in groupe]
        if len(membres) != len(groupe):
            # Groupe incomplet : renormaliser sur une partie fausserait les
            # probabilités au lieu de les corriger.
            continue
        somme = sum(float(p["probability"]) for p in membres)
        if somme <= SOMME_MINIMALE:
            continue
        for p in membres:
            p["probability"] = float(p["probability"]) / somme


def appliquer_calibration(
    predictions: list[dict[str, Any]],
    calibrateurs: dict[str, Calibrateur] | None,
    *,
    renormaliser: bool = True,
) -> list[dict[str, Any]]:
    """Calibrer des prédictions, marché par marché.

    Args:
        predictions: prédictions au contrat public, chacune portant au moins
            ``market``, ``selection`` et ``probability``.
        calibrateurs: un calibrateur par marché. Un marché absent de la table
            est laissé tel quel — mieux vaut une probabilité brute qu'une
            probabilité corrigée par un calibrateur appris ailleurs.
        renormaliser: ramener les groupes exclusifs à une somme de 1. À laisser
            vrai hors test : une somme différente de 1 fausse l'edge et toute
            probabilité jointe.

    Returns:
        Une nouvelle liste. Les prédictions reçues ne sont pas modifiées : le
        `fair_odds` d'origine reste consultable pour comparer.
    """
    if not calibrateurs:
        return [dict(p) for p in predictions]

    resultat = [dict(p) for p in predictions]
    par_marche: dict[str, list[dict[str, Any]]] = {}
    for p in resultat:
        par_marche.setdefault(str(p.get("market")), []).append(p)

    calibres = 0
    for marche, lot in par_marche.items():
        calibrateur = calibrateurs.get(marche)
        if calibrateur is None:
            continue
        brutes = [float(p["probability"]) for p in lot]
        corrigees = calibrateur.transform(brutes)
        for p, valeur in zip(lot, corrigees, strict=True):
            p["probability"] = float(valeur)
        calibres += len(lot)

        if renormaliser:
            _renormaliser(lot, marche)

    # La cote équitable dérive de la probabilité : la laisser inchangée
    # reviendrait à publier un prix qui ne correspond plus à la probabilité
    # affichée juste à côté.
    for p in resultat:
        probabilite = float(p["probability"])
        if probabilite > SOMME_MINIMALE:
            p["fair_odds"] = 1.0 / probabilite

    if calibres:
        logger.debug(f"{calibres} probabilités calibrées sur {len(resultat)}")
    return resultat


def charger_calibrateurs(
    model_version: str, registry_dir: str | None = None
) -> dict[str, Calibrateur]:
    """Charger les calibrateurs enregistrés pour une version de modèle.

    Retourne une table vide si aucun n'a été ajusté : le pipeline continue alors
    sur les probabilités brutes, ce qui est le comportement d'avant la
    calibration et non une erreur.
    """
    from models.model_registry import ModelRegistry

    registre = ModelRegistry(registry_dir) if registry_dir else ModelRegistry()
    payload = registre.load(NOM_MODELE, model_version)
    if not payload:
        logger.info(
            f"Aucun calibrateur enregistré pour {model_version!r} : "
            "les probabilités brutes sont utilisées."
        )
        return {}

    calibrateurs = {
        marche: Calibrateur.from_dict(donnees)
        for marche, donnees in payload.get("par_marche", {}).items()
    }
    logger.info(f"{len(calibrateurs)} calibrateurs chargés : {sorted(calibrateurs)}")
    return calibrateurs


NOM_MODELE = "calibrateur"

__all__ = ["NOM_MODELE", "appliquer_calibration", "charger_calibrateurs"]
