"""Confrontation des probabilités du modèle aux prix du marché.

`PROJECT_SPEC.md` définit l'``edge`` comme l'écart entre la probabilité du
modèle et la probabilité de marché, celle-ci obtenue en normalisant les
probabilités brutes d'un bookmaker pour en retirer la marge :

.. math::

    p_{brut} = 1 / cote
    \\qquad
    p_{marché} = p_{brut} / \\sum p_{brut}
    \\qquad
    edge = p_{modèle} - p_{marché}

Deux prix distincts sont nécessaires, et les confondre fausse tout :

- **le prix auquel on parierait** : la meilleure cote disponible, celle qui
  détermine le rendement réel. C'est elle qui est stockée en ``offered_odds`` ;
- **le prix de référence** : les cotes d'un bookmaker au marché complet, dont
  on retire la marge pour estimer la probabilité de marché. Le bookmaker à la
  plus faible marge est retenu : c'est le mieux informé.

Le backtest précédent utilisait la cote du modèle lui-même comme prix de pari.
Le rendement calculé était alors une tautologie : parier à sa propre cote
équitable ne peut structurellement rien rapporter.

Ce module ne consulte que des cotes **pré-match**. Les cotes de clôture ont
leur propre usage — servir d'étalon d'évaluation, comme le demande la
définition de réussite — mais elles ne doivent jamais alimenter un ``edge``
présenté comme disponible au moment de prédire.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.models import OddsSnapshot, Prediction
from models.market_assembly import GROUPES_EXCLUSIFS

# Les groupes de sélections exclusives sont déclarés une seule fois, avec le
# contrat public des marchés : c'est la même notion qui sert ici à mesurer la
# marge d'un bookmaker et, dans le backtest, à définir une accuracy.
GROUPES_DE_MARCHE = GROUPES_EXCLUSIFS


def _cotes_du_match(session, match_id: int, *, closing: bool) -> list[OddsSnapshot]:
    return (
        session.query(OddsSnapshot)
        .filter(OddsSnapshot.match_id == match_id, OddsSnapshot.is_closing.is_(closing))
        .all()
    )


def meilleures_cotes(cotes: list[OddsSnapshot]) -> dict[tuple[str, str], float]:
    """Meilleure cote disponible par (marché, sélection).

    C'est le prix qu'un parieur obtiendrait réellement en comparant les
    bookmakers.
    """
    meilleures: dict[tuple[str, str], float] = {}
    for cote in cotes:
        if cote.odds is None or cote.odds <= 1.0:
            continue
        cle = (cote.market, cote.selection)
        if cote.odds > meilleures.get(cle, 0.0):
            meilleures[cle] = float(cote.odds)
    return meilleures


def probabilites_de_marche(cotes: list[OddsSnapshot]) -> dict[tuple[str, str], float]:
    """Probabilités de marché, marge retirée, par (marché, sélection).

    Pour chaque groupe de sélections formant un marché complet, on retient le
    bookmaker à la plus faible marge — le mieux informé — puis on normalise ses
    probabilités brutes. Un groupe incomplet est ignoré : sans toutes les
    issues, la marge n'est pas mesurable et la normalisation serait fausse.
    """
    par_bookmaker: dict[tuple[str, str, str], float] = {}
    for cote in cotes:
        if cote.odds is None or cote.odds <= 1.0:
            continue
        par_bookmaker[(cote.bookmaker, cote.market, cote.selection)] = float(cote.odds)

    bookmakers = {cle[0] for cle in par_bookmaker}
    probabilites: dict[tuple[str, str], float] = {}

    for marche, groupes in GROUPES_DE_MARCHE.items():
        for groupe in groupes:
            meilleur_bookmaker = None
            marge_minimale = None
            for bookmaker in bookmakers:
                brutes = [
                    1.0 / par_bookmaker[(bookmaker, marche, selection)]
                    for selection in groupe
                    if (bookmaker, marche, selection) in par_bookmaker
                ]
                if len(brutes) != len(groupe):
                    continue  # marché incomplet chez ce bookmaker
                marge = sum(brutes)
                if marge_minimale is None or marge < marge_minimale:
                    marge_minimale, meilleur_bookmaker = marge, bookmaker

            if meilleur_bookmaker is None or not marge_minimale:
                continue
            for selection in groupe:
                brute = 1.0 / par_bookmaker[(meilleur_bookmaker, marche, selection)]
                probabilites[(marche, selection)] = brute / marge_minimale

    return probabilites


def valoriser_predictions(
    session,
    match_id: int,
    model_version: str | None = None,
    *,
    closing: bool = False,
) -> int:
    """Renseigner ``offered_odds`` et ``edge`` sur les prédictions d'un match.

    Args:
        session: session SQLAlchemy.
        match_id: match concerné.
        model_version: restreindre à une version de modèle, ou toutes.
        closing: utiliser les cotes de clôture. Réservé à l'évaluation
            rétrospective : ces cotes ne sont pas disponibles au moment de
            prédire, et le résultat ne doit jamais être présenté comme un edge
            exploitable.

    Returns:
        Le nombre de prédictions valorisées. Ne commite pas.
    """
    cotes = _cotes_du_match(session, match_id, closing=closing)
    if not cotes:
        return 0

    prix = meilleures_cotes(cotes)
    marche = probabilites_de_marche(cotes)

    requete = session.query(Prediction).filter_by(match_id=match_id)
    if model_version is not None:
        requete = requete.filter_by(model_version=model_version)

    valorisees = 0
    for prediction in requete.all():
        cle = (prediction.market, prediction.selection)
        if cle in prix:
            prediction.offered_odds = prix[cle]
        if cle in marche and prediction.probability is not None:
            prediction.edge = float(prediction.probability) - marche[cle]
        if cle in prix or cle in marche:
            valorisees += 1

    return valorisees


def valoriser_toutes_les_predictions(
    session,
    model_version: str | None = None,
    *,
    closing: bool = False,
) -> dict[str, Any]:
    """Valoriser toutes les prédictions en base, match par match."""
    requete = session.query(Prediction.match_id).distinct()
    if model_version is not None:
        requete = requete.filter(Prediction.model_version == model_version)

    match_ids = [row[0] for row in requete.all()]
    total = 0
    for match_id in match_ids:
        total += valoriser_predictions(session, match_id, model_version, closing=closing)

    session.commit()
    logger.info(f"Valorisation : {total} prédictions sur {len(match_ids)} matchs")
    return {"matchs": len(match_ids), "predictions_valorisees": total}
