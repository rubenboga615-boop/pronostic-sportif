"""Pipeline de génération de prédictions."""

from collections.abc import Sequence
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
        missing = [k for k in ("market", "selection", "probability", "fair_odds") if k not in pred]
        if missing:
            raise ValueError(f"Prédiction incomplète : champs manquants {missing}")

        market = pred["market"]
        selection = pred["selection"]
        probability = pred["probability"]
        fair_odds = pred["fair_odds"]

        if market not in PUBLIC_MARKETS:
            raise ValueError(f"Marché inconnu : {market!r}")
        if selection not in PUBLIC_SELECTIONS.get(market, frozenset()):
            raise ValueError(f"Sélection inconnue : {selection!r} pour le marché {market!r}")
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
                raise ValueError(f"Doublons contradictoires pour {market}/{selection}")
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


def generate_predictions_for_matches(
    session,
    match_ids: Sequence[int],
    model_version: str = "poisson-v1",
) -> dict[str, Any]:
    """Générer et persister les prédictions pour une liste explicite de matchs.

    Transaction indépendante par match : chaque ``generate_match_predictions``
    est commitée individuellement. Une erreur sur un match n'affecte pas les
    autres. Les exceptions ne sont jamais masquées.

    Args:
        session: Session SQLAlchemy.
        match_ids: Liste explicite des ``match_id`` à traiter.
        model_version: Version du modèle (défaut ``"poisson-v1"``).

    Returns:
        ``{``
            ``"succeeded": [match_id, ...],``
            ``"failed": [{"match_id": int, "error": str}, ...],``
            ``"predictions_created_or_updated": int,``
        ``}``
    """
    succeeded: list[int] = []
    failed: list[dict[str, Any]] = []
    total_predictions = 0

    for match_id in match_ids:
        try:
            results = generate_match_predictions(session, match_id, model_version)
            succeeded.append(match_id)
            total_predictions += len(results)
        except Exception as exc:
            failed.append({"match_id": match_id, "error": str(exc)})

    return {
        "succeeded": succeeded,
        "failed": failed,
        "predictions_created_or_updated": total_predictions,
    }


def _select_matches_ready_for_prediction(session, reference_date) -> list[int]:
    """Sélectionner les matchs pour lesquels générer des prédictions.

    Règle temporelle (date de coupure) :
    -------------------------------
    La prédiction pré-match ne concerne que les matchs dont la date est
    **strictement postérieure** à la date de référence fournie explicitement
    par l'appelant : ``match_date > reference_date``.

    - Un match daté à la date de référence ou avant est considéré comme déjà
      connu (terminé ou en cours) et n'est **jamais** sélectionné, même si ses
      features existent : la présence de features ne rend pas un match passé
      prédictible.
    - ``reference_date`` est obligatoire et fournie par l'appelant : la
      fonction n'appelle jamais ``datetime.now()`` elle-même (aucune
      dépendance implicite au moment de l'exécution, résultat déterministe et
      testable).
    - Les matchs sans ``match_date`` sont exclus.
    - Les matchs sans ``Feature`` domicile **et** extérieure sont exclus.
    - Le tri chronologique (``match_date`` puis ``id``) rend le résultat
      déterministe ; ``id`` n'est pas utilisé comme indicateur chronologique.

    Args:
        session: Session SQLAlchemy.
        reference_date: Date de coupure des données. Seuls les matchs avec
            ``match_date > reference_date`` sont retenus.

    Returns:
        Liste triée des ``match_id`` éligibles.

    Raises:
        ValueError: si ``reference_date`` est ``None``.
    """
    if reference_date is None:
        raise ValueError(
            "reference_date est obligatoire : la date de coupure doit être "
            "fournie explicitement par l'appelant"
        )

    from sqlalchemy import orm

    from app.models import Feature

    fh = orm.aliased(Feature)
    fa = orm.aliased(Feature)

    rows = (
        session.query(Match.id)
        .join(fh, (fh.match_id == Match.id) & (fh.team_id == Match.home_team_id))
        .join(fa, (fa.match_id == Match.id) & (fa.team_id == Match.away_team_id))
        .filter(Match.match_date.isnot(None))
        .filter(Match.match_date > reference_date)
        .order_by(Match.match_date, Match.id)
        .all()
    )
    return [row[0] for row in rows]


def run_prediction_pipeline(
    engine=None,
    model_version: str = "poisson-v1",
    *,
    reference_date,
) -> dict[str, Any]:
    """Exécuter le pipeline de prédiction.

    Sélectionne les matchs prêts dont la date est strictement postérieure à la
    date de référence, génère les prédictions via
    ``generate_predictions_for_matches``, et retourne un rapport structuré.

    Règle temporelle : seul un match avec ``match_date > reference_date`` est
    prédit. Les matchs passés ou datés à la date de coupure sont exclus même
    si leurs features existent (voir ``_select_matches_ready_for_prediction``).

    Transaction indépendante par match (via ``generate_predictions_for_matches``).

    Args:
        engine: Moteur SQLAlchemy. Si ``None``, utilise ``app.database.engine``.
        model_version: Version du modèle (défaut ``"poisson-v1"``).
        reference_date: Date de coupure des données (obligatoire, keyword-only).
            L'appelant la fournit explicitement — typiquement ``datetime.now()``
            pour une exécution quotidienne, ou une date fixe dans les tests.
            Le pipeline ne l'infère jamais lui-même.

    Returns:
        Rapport ``{succeeded, failed, predictions_created_or_updated}``.

    Raises:
        ValueError: si ``reference_date`` est ``None``.
    """
    if reference_date is None:
        raise ValueError(
            "reference_date est obligatoire : la date de coupure doit être "
            "fournie explicitement par l'appelant"
        )

    from app.database import SessionLocal

    if engine is None:
        from app.database import engine as default_engine

        engine = default_engine

    logger.info("=== Début du pipeline de prédiction ===")

    session = SessionLocal(bind=engine)
    try:
        # Étape 1 : Sélection des matchs prêts (match_date > reference_date)
        logger.info("Étape 1 : Sélection des matchs prêts...")
        logger.info(f"  Règle temporelle : match_date > {reference_date.isoformat()}")
        match_ids = _select_matches_ready_for_prediction(session, reference_date)
        logger.info(f"  {len(match_ids)} matchs sélectionnés")

        if not match_ids:
            logger.info("Aucun match à prédire.")
            logger.info("=== Fin du pipeline de prédiction ===")
            return {
                "succeeded": [],
                "failed": [],
                "predictions_created_or_updated": 0,
            }

        # Étape 2 : Génération des prédictions
        logger.info("Étape 2 : Génération des prédictions...")
        report = generate_predictions_for_matches(session, match_ids, model_version)

        logger.info(
            f"  {report['predictions_created_or_updated']} prédictions "
            f"({len(report['succeeded'])} réussies, "
            f"{len(report['failed'])} échouées)"
        )

        if report["failed"]:
            for f in report["failed"]:
                logger.warning(f"  Match {f['match_id']} échoué : {f['error']}")

        logger.info("=== Fin du pipeline de prédiction ===")
        return report
    except Exception:
        logger.error("Erreur fatale dans le pipeline de prédiction")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    # Date de coupure fournie explicitement par le point d'entrée CLI :
    # prédire uniquement les matchs strictement postérieurs à maintenant.
    run_prediction_pipeline(reference_date=datetime.now())
