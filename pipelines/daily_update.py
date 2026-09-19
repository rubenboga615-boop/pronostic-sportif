"""La journée type du moteur : collecter, prédire, régler.

Ce pipeline est le seul du projet dont l'absence coûte quelque chose
d'irrattrapable. **API-Football n'archive pas ses cotes** — vérifié le
19/09/2026 : `odds?league=39&season=2024` rend zéro entrée, quand le même
appel sur la saison en cours en rend des milliers. Une cote non relevée
aujourd'hui n'existera plus demain, et six des huit marchés de la Phase 1 ne
peuvent être mesurés que sur des relevés faits en avant. Chaque journée
manquée est une journée de preuve perdue.

D'où la forme du pipeline : il fait peu de choses, mais il les fait tous les
jours, et il les fait deux fois.

**Deux relevés de cotes par jour, pas un.** Tout le projet mesure le rendement
contre les cotes de **clôture** — les 3 504 matchs déjà mesurés le sont. Un
relevé de la veille ne leur est pas comparable. Le passage marqué
``--cloture``, lancé dans l'heure qui précède les coups d'envoi, écrit donc des
relevés portant ``is_closing = True``. L'écart entre les deux passages remplit
au passage ``odds_movement``, une variable écrite depuis le premier jour du
projet et qui n'a jamais eu de données.

**Les résultats avant les prédictions.** Importer les scores de la veille met à
jour les features, et c'est sur ces features que les prédictions du jour sont
calculées. L'ordre inverse prédirait avec la forme de l'avant-veille.

**Aucune étape n'interrompt les suivantes.** Le réseau de cette machine tombe
par intermittence ; un relevé de cotes manqué ne doit pas empêcher le règlement
des matchs joués, qui ne demande, lui, aucun réseau.

Usage :
    python -m pipelines.daily_update                  # passage du matin
    python -m pipelines.daily_update --cloture        # juste avant les matchs
    python -m pipelines.daily_update --version dc-live --jours 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

VERSION_PAR_DEFAUT = "dc-live"

# Fenêtre de cotes, en jours. Trois couvre un week-end entier depuis le
# vendredi ; au-delà, les bookmakers n'ont souvent pas encore ouvert leurs
# marchés et l'appel revient vide.
JOURS_PAR_DEFAUT = 3


@dataclass
class RapportJournalier:
    """Ce que la journée a produit, étape par étape."""

    debut: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    cloture: bool = False
    etapes: dict[str, Any] = field(default_factory=dict)
    echecs: list[dict[str, str]] = field(default_factory=list)

    def reussite(self, etape: str, detail: Any) -> None:
        self.etapes[etape] = detail
        logger.info(f"  ✓ {etape} : {detail}")

    def echec(self, etape: str, erreur: Exception) -> None:
        self.echecs.append({"etape": etape, "erreur": str(erreur)})
        logger.error(f"  ✗ {etape} : {erreur}")

    def en_dict(self) -> dict[str, Any]:
        return {
            "debut": self.debut,
            "fin": datetime.now(UTC).isoformat(),
            "cloture": self.cloture,
            "etapes": self.etapes,
            "echecs": self.echecs,
        }


def _dates_a_relever(jours: int) -> list[str]:
    aujourdhui = datetime.now(UTC).date()
    return [(aujourdhui + timedelta(days=n)).isoformat() for n in range(jours)]


def _saison_courante(maintenant: datetime | None = None) -> int:
    """Saison API en cours. Une saison bascule en juillet, pas en janvier."""
    maintenant = maintenant or datetime.now(UTC)
    return maintenant.year if maintenant.month >= 7 else maintenant.year - 1


# ──────────────────────────────────────────────
# Les étapes
# ──────────────────────────────────────────────


def etape_matchs(session, client, rapport: RapportJournalier) -> None:
    """Importer résultats de la veille et calendrier à venir, en un appel par ligue."""
    from pipelines.api_football_import import Rapport, importer_matchs

    interne = Rapport()
    asyncio.run(importer_matchs(session, client, _saison_courante(), rapport=interne))
    rapport.reussite(
        "matchs",
        {
            "crees": interne.matchs_crees,
            "mis_a_jour": interne.matchs_mis_a_jour,
            "equipes_creees": interne.equipes_creees,
            "appels": interne.appels,
        },
    )
    if interne.equipes_creees:
        logger.warning(
            f"Équipes créées sans historique : {', '.join(interne.equipes_creees)}. "
            "Leurs forces reposeront sur quelques matchs — voir SIGMA_FORCES."
        )


def etape_blessures(session, client, rapport: RapportJournalier) -> None:
    """Relever les indisponibilités déclarées pour les matchs à venir.

    C'est la seule information de ce corpus que le marché peut intégrer avec
    retard : un bookmaker ajuste vite après l'annonce d'une absence, mais pas
    instantanément. Vérifié le 19/09/2026, ces entrées sont bien publiées
    avant le coup d'envoi — 26 joueurs pour un match du matin, relevés la nuit
    précédente.
    """
    from pipelines.api_football_import import Rapport, importer_blessures

    interne = Rapport()
    asyncio.run(importer_blessures(session, client, _saison_courante(), rapport=interne))
    rapport.reussite(
        "blessures",
        {
            "inserees": interne.blessures_inserees,
            "deja_connues": interne.blessures_deja_presentes,
            "appels": interne.appels,
        },
    )


def etape_features(rapport: RapportJournalier) -> None:
    """Recalculer les features, résultats de la veille compris.

    Le recalcul est complet et non incrémental : c'est le comportement du
    pipeline existant, et à dix-sept millisecondes par match il reste tenable.
    """
    from pipelines.feature_pipeline import run_feature_pipeline

    rapport.reussite("features", run_feature_pipeline())


def etape_cotes(session, client, jours: int, cloture: bool, rapport: RapportJournalier) -> None:
    """Relever les cotes des matchs à venir.

    ``cloture`` marque les relevés comme cotes de clôture. À ne lancer que dans
    l'heure précédant les coups d'envoi : une cote relevée la veille et
    étiquetée « clôture » rendrait tout rendement incomparable aux mesures
    passées, sans qu'aucune erreur ne le signale.
    """
    from pipelines.api_football_import import Rapport, importer_cotes

    interne = Rapport()
    dates = _dates_a_relever(1 if cloture else jours)
    asyncio.run(importer_cotes(session, client, dates, rapport=interne, cloture=cloture))
    rapport.reussite(
        "cotes",
        {
            "inserees": interne.cotes_inserees,
            "deja_presentes": interne.cotes_deja_presentes,
            "cloture": cloture,
            "appels": interne.appels,
        },
    )


def etape_reglement(session, rapport: RapportJournalier) -> None:
    """Régler les matchs joués. Aucun réseau : cette étape aboutit toujours."""
    from evaluation.settlement import regler_les_matchs_termines

    resultat = regler_les_matchs_termines(session)
    rapport.reussite(
        "reglement",
        {"matchs": resultat["matchs_regles"], "lignes": resultat["lignes_ecrites"]},
    )


def etape_predictions(version: str, rapport: RapportJournalier) -> None:
    """Prédire les matchs à venir, avec le modèle de chaque championnat."""
    from scripts.generate_predictions import predire

    rapports = predire(
        version=version,
        reference_date=datetime.now(),
        valoriser=True,
        # Jamais les cotes de clôture ici : elles sont relevées au coup
        # d'envoi et ne sont pas connues au moment de prédire. Les utiliser
        # serait une fuite, et gonflerait le rendement mesuré.
        cotes_de_cloture=False,
    )
    rapport.reussite(
        "predictions",
        {
            f"competition_{identifiant}": r.get("predictions_generees", 0)
            for identifiant, r in rapports.items()
        },
    )


def etape_sauvegarde(rapport: RapportJournalier) -> None:
    """Sauvegarder la base. Dernière étape : elle capture le résultat du jour."""
    import shutil

    from app.config import settings

    source = Path("data/pronostic.db")
    if not source.exists():
        raise FileNotFoundError(f"Base introuvable : {source}")
    dossier = Path(settings.backups_dir)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"pronostic_quotidien_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(source, cible)
    rapport.reussite("sauvegarde", str(cible))


# ──────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────


def run_daily_update(
    version: str = VERSION_PAR_DEFAUT,
    jours: int = JOURS_PAR_DEFAUT,
    cloture: bool = False,
    client=None,
    session=None,
    repertoire_rapports: str = "rapports",
) -> RapportJournalier:
    """Exécuter la journée type.

    Args:
        version: racine de version des modèles, sans le suffixe ``-comp{id}``.
        jours: fenêtre de relevé des cotes, en jours.
        cloture: relever les cotes de clôture plutôt que les cotes courantes.
            Réservé au passage précédant les coups d'envoi.
        client: client API-Football. Injecté par les tests.
        session: session SQLAlchemy. Injectée par les tests.
        repertoire_rapports: où écrire le rapport ; ``""`` pour ne pas en écrire.

    Returns:
        Le rapport de la journée, échecs compris.
    """
    rapport = RapportJournalier(cloture=cloture)
    logger.info(
        f"=== Journée du {datetime.now(UTC).date()} "
        f"{'(relevé de clôture)' if cloture else '(passage courant)'} ==="
    )

    if client is None:
        from collectors.api_football.client import ClientApiFootball

        client = ClientApiFootball()

    ferme_la_session = session is None
    if session is None:
        from app.database import SessionLocal

        session = SessionLocal()

    try:
        # Un passage de clôture ne fait qu'une chose, et vite : relever les
        # cotes avant le coup d'envoi. Tout le reste attendra le lendemain.
        if cloture:
            etapes = [("cotes", lambda: etape_cotes(session, client, jours, True, rapport))]
        else:
            etapes = [
                ("matchs", lambda: etape_matchs(session, client, rapport)),
                ("blessures", lambda: etape_blessures(session, client, rapport)),
                ("features", lambda: etape_features(rapport)),
                ("reglement", lambda: etape_reglement(session, rapport)),
                ("cotes", lambda: etape_cotes(session, client, jours, False, rapport)),
                ("predictions", lambda: etape_predictions(version, rapport)),
                ("sauvegarde", lambda: etape_sauvegarde(rapport)),
            ]

        for nom, executer in etapes:
            logger.info(f"Étape : {nom}")
            try:
                executer()
            except Exception as erreur:  # noqa: BLE001 — aucune étape n'arrête les suivantes
                rapport.echec(nom, erreur)
    finally:
        if ferme_la_session:
            session.close()

    if repertoire_rapports:
        dossier = Path(repertoire_rapports)
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = dossier / f"journee_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        fichier.write_text(
            json.dumps(rapport.en_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info(f"Rapport : {fichier}")

    if rapport.echecs:
        logger.warning(f"{len(rapport.echecs)} étape(s) en échec — la journée reste exploitable")
    logger.info("=== Journée terminée ===")
    return rapport


def main() -> None:
    parser = argparse.ArgumentParser(description="Journée type du moteur")
    parser.add_argument("--version", default=VERSION_PAR_DEFAUT, help="Racine de version du modèle")
    parser.add_argument(
        "--jours", type=int, default=JOURS_PAR_DEFAUT, help="Fenêtre de cotes, en jours"
    )
    parser.add_argument(
        "--cloture",
        action="store_true",
        help="Relever les cotes de clôture ; à lancer dans l'heure précédant les coups d'envoi",
    )
    args = parser.parse_args()
    run_daily_update(version=args.version, jours=args.jours, cloture=args.cloture)


if __name__ == "__main__":
    main()
