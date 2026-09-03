"""Pipeline de génération de prédictions."""

from datetime import datetime
from typing import Any

from loguru import logger

from app.models import Match, Prediction
from models.market_assembly import PUBLIC_MARKETS, PUBLIC_SELECTIONS
from models.prediction_context import build_match_predictions


def persist_predictions(
    session,
    match_id: int,
    model_version: str,
    predictions: list[dict[str, Any]],
) -> list[Prediction]:
    """Persister de façon idempotente les prédictions d'un match.

    Clé logique applicative : ``(match_id, model_version, market, selection)``.
    Valide toutes les prédictions **avant** toute écriture, puis insère ou met à
    jour chaque ligne (``probability``, ``fair_odds``, ``generated_at``). Un seul
    ``commit`` en fin de traitement ; ``rollback`` puis re-levée en cas
    d'exception.
    """
    if session.get(Match, match_id) is None:
        raise LookupError(f"Match {match_id} introuvable")

    validated = _validate_predictions(predictions)

    try:
        results: list[Prediction] = []
        for p in validated:
            existing = (
                session.query(Prediction)
                .filter_by(
                    match_id=match_id,
                    model_version=model_version,
                    market=p["market"],
                    selection=p["selection"],
                )
                .first()
            )
            if existing is None:
                obj = Prediction(
                    match_id=match_id,
                    model_version=model_version,
                    market=p["market"],
                    selection=p["selection"],
                    probability=p["probability"],
                    fair_odds=p["fair_odds"],
                )
                session.add(obj)
                results.append(obj)
            else:
                existing.probability = p["probability"]
                existing.fair_odds = p["fair_odds"]
                existing.generated_at = datetime.utcnow()
                results.append(existing)
        session.commit()
        return results
    except Exception:
        session.rollback()
        raise


def _validate_predictions(
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Valider et dédupliquer les prédictions (avant toute écriture)."""
    validated: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}

    for pred in predictions:
        missing = [
            k for k in ("market", "selection", "probability", "fair_odds")
            if k not in pred
        ]
        if missing:
            raise ValueError(f"Prédiction incomplète : champs manquants {missing}")

        market = pred["market"]
        selection = pred["selection"]
        probability = pred["probability"]
        fair_odds = pred["fair_odds"]

        if market not in PUBLIC_MARKETS:
            raise ValueError(f"Marché inconnu : {market!r}")
        if selection not in PUBLIC_SELECTIONS.get(market, frozenset()):
            raise ValueError(
                f"Sélection inconnue : {selection!r} pour le marché {market!r}"
            )
        if probability is None or not (0.0 <= probability <= 1.0):
            raise ValueError(f"Probability hors [0, 1] : {probability!r}")
        if fair_odds is None or not (fair_odds > 0):
            raise ValueError(f"fair_odds doit être strictement positive : {fair_odds!r}")

        item = {
            "market": market,
            "selection": selection,
            "probability": probability,
            "fair_odds": fair_odds,
        }
        key = (market, selection)
        if key in seen:
            if seen[key] != item:
                raise ValueError(
                    f"Doublons contradictoires pour {market}/{selection}"
                )
            continue  # doublon identique : ignoré
        seen[key] = item
        validated.append(item)

    return validated


def generate_match_predictions(
    session,
    match_id: int,
    model_version: str = "poisson-v1",
) -> list[Prediction]:
    """Générer et persister les prédictions d'un match (anti-fuite, idempotent).

    Enchaîne : contexte anti-fuite (``build_match_predictions``) → persistance
    idempotente (``persist_predictions``). Un second appel sur le même match met
    à jour les lignes existantes sans créer de doublon.
    """
    predictions = build_match_predictions(session, match_id)
    return persist_predictions(session, match_id, model_version, predictions)


def run_prediction_pipeline() -> None:
    """Exécuter le pipeline de prédiction.
    
    Étapes :
    1. Charger les matchs à venir
    2. Calculer les features
    3. Charger le modèle
    4. Générer les prédictions
    5. Dériver les marchés
    6. Sauvegarder les résultats
    """
    logger.info("=== Début du pipeline de prédiction ===")

    # Étape 1 : Matchs à venir
    logger.info("Étape 1 : Chargement des matchs à venir...")
    # TODO: implémenter

    # Étape 2 : Features
    logger.info("Étape 2 : Calcul des features...")
    # TODO: implémenter

    # Étape 3 : Modèle
    logger.info("Étape 3 : Chargement du modèle...")
    # TODO: implémenter

    # Étape 4 : Prédictions
    logger.info("Étape 4 : Génération des prédictions...")
    # TODO: implémenter

    # Étape 5 : Dérivation des marchés
    logger.info("Étape 5 : Dérivation des marchés...")
    # TODO: implémenter avec models.market_derivation

    # Étape 6 : Sauvegarde
    logger.info("Étape 6 : Sauvegarde des résultats...")
    # TODO: implémenter

    logger.info("=== Fin du pipeline de prédiction ===")


if __name__ == "__main__":
    run_prediction_pipeline()
