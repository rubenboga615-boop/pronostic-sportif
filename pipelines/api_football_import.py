"""Importer en base les matchs et les cotes d'API-Football.

C'est la pièce qui manquait pour que le projet regarde vers l'avant. Jusqu'ici
tout venait de Football-Data : des matchs joués, avec leur score et leurs cotes
de clôture. Un match à venir n'a ni l'un ni l'autre, et c'est la seule raison
pour laquelle le moteur n'avait jamais prédit quoi que ce soit d'incertain.

Quatre règles gouvernent l'écriture, et chacune répare une façon précise de
corrompre la base.

**Compléter, jamais écraser.** 17 251 matchs et 363 372 cotes viennent de
Football-Data et font autorité. Un match déjà présent n'est mis à jour que sur
les colonnes réellement vides, et le score d'un match déjà réglé n'est jamais
touché — D-10 l'interdit hors migration versionnée.

**Les équipes sont partagées, pas dupliquées.** La recherche se fait sur le nom
canonique sans filtrer le fournisseur : Brest doit rester Brest, avec ses douze
saisons, qu'on le découvre par un CSV ou par une API. Créer une équipe est
signalé dans le rapport, jamais silencieux.

**Un match à venir n'a pas de résultat, et c'est normal.** Il entre avec le
statut ``scheduled``, ses buts à ``NULL``. Le pipeline de features n'en tirera
rien — c'est voulu, la règle anti-fuite l'exige : un match sans résultat ne
doit alimenter aucune variable.

**L'import est rejouable.** Le réseau de cette machine tombe par intermittence.
Chaque appel est réessayé plus patiemment que ne le fait le client, chaque lot
est écrit dans sa propre transaction, et relancer l'import après une coupure ne
crée aucun doublon : l'identifiant du fournisseur fait clé.

Usage :
    python -m pipelines.api_football_import --matchs
    python -m pipelines.api_football_import --cotes --jours 3
    python -m pipelines.api_football_import --matchs --cotes --dry-run
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
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Match, OddsSnapshot, Season, Team
from collectors.api_football.client import ClientApiFootball
from collectors.api_football.erreurs import ApiFootballError
from collectors.api_football.ligues import LIGUES
from collectors.api_football.parsers import (
    CoteNormalisee,
    MatchNormalise,
    parser_cotes,
    parser_fixtures,
    saison_football_data,
)
from collectors.mapping.registre import charger_registre

FOURNISSEUR = "api_football"

# Le client réessaie trois fois, espacées de quelques secondes. Ici la
# résolution DNS tombe pour des minutes entières : il faut attendre plus
# longtemps qu'échouer vite, sous peine de perdre un import à moitié écrit.
TENTATIVES = 8
ATTENTE = 12.0


@dataclass
class Rapport:
    """Ce qu'un import a fait, dans le détail, pour être relu."""

    matchs_crees: int = 0
    matchs_mis_a_jour: int = 0
    matchs_inchanges: int = 0
    equipes_creees: list[str] = field(default_factory=list)
    cotes_inserees: int = 0
    cotes_deja_presentes: int = 0
    ignores: list[dict] = field(default_factory=list)
    appels: int = 0

    def en_dict(self) -> dict[str, Any]:
        return {
            "horodatage": datetime.now(UTC).isoformat(),
            "matchs_crees": self.matchs_crees,
            "matchs_mis_a_jour": self.matchs_mis_a_jour,
            "matchs_inchanges": self.matchs_inchanges,
            "equipes_creees": self.equipes_creees,
            "cotes_inserees": self.cotes_inserees,
            "cotes_deja_presentes": self.cotes_deja_presentes,
            "appels": self.appels,
            "ignores": self.ignores,
        }


async def appeler(client, endpoint: str, params: dict, rapport: Rapport) -> dict | None:
    """Appeler un endpoint en tolérant les coupures réseau de cette machine."""
    derniere: Exception | None = None
    for tentative in range(1, TENTATIVES + 1):
        try:
            reponse = await client.get(endpoint, params=params)
            rapport.appels += 1
            return reponse
        except ApiFootballError as erreur:
            derniere = erreur
            if tentative < TENTATIVES:
                await asyncio.sleep(ATTENTE)
    logger.error(f"{endpoint} {params} abandonné après {TENTATIVES} tentatives : {derniere}")
    rapport.ignores.append({"motif": f"{endpoint} injoignable : {derniere}", **params})
    return None


# ──────────────────────────────────────────────
# Résolution des entités
# ──────────────────────────────────────────────


def _competition(session, code_ligue: str):
    """La compétition d'un code Football-Data. Elle existe : l'import historique l'a créée."""
    from app.models import Competition

    return session.execute(
        select(Competition).where(Competition.provider_code == code_ligue)
    ).scalar_one_or_none()


def _saison(session, competition_id: int, nom_saison: str) -> Season:
    """La saison, créée si elle manque — 2026/27 n'existe dans aucune base d'hier."""
    saison = session.execute(
        select(Season).where(
            Season.competition_id == competition_id, Season.season_name == nom_saison
        )
    ).scalar_one_or_none()
    if saison:
        return saison
    debut = 2000 + int(nom_saison[:2])
    saison = Season(
        competition_id=competition_id,
        season_name=nom_saison,
        start_date=datetime(debut, 8, 1),
        end_date=datetime(debut + 1, 5, 31),
        status="in_progress",
    )
    session.add(saison)
    session.flush()
    logger.info(f"Saison créée : {nom_saison} (compétition {competition_id})")
    return saison


def _equipe(session, nom_canonique: str, pays: str, rapport: Rapport) -> Team:
    """L'équipe portant ce nom canonique, créée si elle est inconnue.

    La recherche ignore volontairement la colonne ``provider`` : le nom
    canonique est l'identité partagée entre toutes les sources, et filtrer
    dessus créerait un second « Brest » sans historique.

    Une équipe créée ici est un promu que la base n'a jamais vu. Elle est
    consignée dans le rapport, car Dixon-Coles l'estimera mal tant qu'elle
    n'aura que quelques matchs, et cette faiblesse doit être annoncée plutôt
    que découverte dans une prédiction.
    """
    equipe = session.execute(
        select(Team).where(Team.canonical_name == nom_canonique)
    ).scalar_one_or_none()
    if equipe:
        return equipe
    equipe = Team(
        canonical_name=nom_canonique,
        country=pays,
        # Le nom canonique appartient à l'espace de noms Football-Data, même
        # lorsque c'est API-Football qui nous fait découvrir le club : le
        # déclarer autrement ferait créer un doublon au prochain import de CSV.
        provider="football_data",
        provider_team_id=nom_canonique.lower().replace(" ", "-"),
        active=True,
    )
    session.add(equipe)
    session.flush()
    rapport.equipes_creees.append(nom_canonique)
    logger.warning(f"Équipe créée, sans historique : {nom_canonique}")
    return equipe


def _match_existant(session, normalise: MatchNormalise, domicile_id: int, exterieur_id: int):
    """Retrouver un match déjà en base, par identifiant fournisseur puis par affiche.

    Les deux recherches sont nécessaires. La première rend l'import rejouable.
    La seconde évite de dupliquer un match que Football-Data aurait déjà
    importé — les deux sources ne se recouvrent pas aujourd'hui, mais rien ne
    garantit qu'elles ne se recouvriront jamais.
    """
    par_identifiant = session.execute(
        select(Match).where(
            Match.provider == FOURNISSEUR,
            Match.provider_match_id == normalise.provider_match_id,
        )
    ).scalar_one_or_none()
    if par_identifiant:
        return par_identifiant

    veille = normalise.date - timedelta(days=1)
    lendemain = normalise.date + timedelta(days=1)
    return (
        session.execute(
            select(Match).where(
                Match.home_team_id == domicile_id,
                Match.away_team_id == exterieur_id,
                Match.match_date >= veille,
                Match.match_date <= lendemain,
            )
        )
        .scalars()
        .first()
    )


# ──────────────────────────────────────────────
# Écriture des matchs
# ──────────────────────────────────────────────


def _ecrire_match(session, normalise: MatchNormalise, rapport: Rapport) -> Match | None:
    """Créer ou compléter un match. Ne réécrit jamais un résultat déjà en base."""
    competition = _competition(session, normalise.code_ligue)
    if competition is None:
        rapport.ignores.append(
            {"motif": "compétition absente de la base", "ligue": normalise.code_ligue}
        )
        return None

    pays = LIGUES[normalise.code_ligue][2]
    domicile = _equipe(session, normalise.domicile, pays, rapport)
    exterieur = _equipe(session, normalise.exterieur, pays, rapport)
    saison = _saison(session, competition.id, normalise.saison)

    existant = _match_existant(session, normalise, domicile.id, exterieur.id)
    if existant is None:
        session.add(
            Match(
                provider=FOURNISSEUR,
                provider_match_id=normalise.provider_match_id,
                competition_id=competition.id,
                season_id=saison.id,
                match_date=normalise.date,
                home_team_id=domicile.id,
                away_team_id=exterieur.id,
                status=normalise.statut,
                home_goals=normalise.buts_domicile,
                away_goals=normalise.buts_exterieur,
                home_ht_goals=normalise.buts_mt_domicile,
                away_ht_goals=normalise.buts_mt_exterieur,
                referee=normalise.arbitre,
            )
        )
        session.flush()
        rapport.matchs_crees += 1
        return session.execute(
            select(Match).where(
                Match.provider == FOURNISSEUR,
                Match.provider_match_id == normalise.provider_match_id,
            )
        ).scalar_one()

    modifie = False
    # Un match passé de « à venir » à « joué » : c'est la seule mise à jour de
    # score autorisée, et seulement parce que la case était vide.
    if existant.home_goals is None and normalise.buts_domicile is not None:
        existant.home_goals = normalise.buts_domicile
        existant.away_goals = normalise.buts_exterieur
        existant.status = normalise.statut
        modifie = True
    if existant.home_ht_goals is None and normalise.buts_mt_domicile is not None:
        existant.home_ht_goals = normalise.buts_mt_domicile
        existant.away_ht_goals = normalise.buts_mt_exterieur
        modifie = True
    if not existant.referee and normalise.arbitre:
        existant.referee = normalise.arbitre
        modifie = True
    if existant.status != normalise.statut and existant.home_goals is None:
        existant.status = normalise.statut
        modifie = True

    rapport.matchs_mis_a_jour += int(modifie)
    rapport.matchs_inchanges += int(not modifie)
    return existant


async def importer_matchs(
    session,
    client,
    saison_api: int,
    codes: list[str] | None = None,
    rapport: Rapport | None = None,
    dry_run: bool = False,
) -> Rapport:
    """Importer le calendrier complet d'une saison, matchs joués compris."""
    rapport = rapport or Rapport()
    registre = charger_registre()
    codes = codes or list(LIGUES)

    for code in codes:
        identifiant, nom, _ = LIGUES[code]
        reponse = await appeler(
            client, "fixtures", {"league": identifiant, "season": saison_api}, rapport
        )
        if reponse is None:
            continue

        table = registre.correspondances.get(FOURNISSEUR, {}).get(code, {})
        parsage = parser_fixtures(reponse.get("response") or [], table, code)
        rapport.ignores.extend(parsage.ignores)
        logger.info(
            f"{code} {nom} : {len(parsage.matchs)} matchs lus, {len(parsage.ignores)} écartés"
        )

        if dry_run:
            continue
        for normalise in parsage.matchs:
            _ecrire_match(session, normalise, rapport)
        session.commit()

    return rapport


# ──────────────────────────────────────────────
# Écriture des cotes
# ──────────────────────────────────────────────


def _ecrire_cotes(session, releves: list[CoteNormalisee], rapport: Rapport) -> None:
    """Insérer des relevés, sans jamais recréer un relevé identique.

    Un relevé est identifié par son match, son bookmaker, son marché, sa
    sélection et son horodatage. Relancer l'import dans la même minute
    n'ajoute rien ; le relancer plus tard ajoute un nouveau point dans le
    temps, ce qui est exactement ce qu'il faut pour suivre le mouvement des
    cotes — la colonne `odds_movement` attend cela depuis le premier jour.

    La session du projet est montée en ``autoflush=False`` : un relevé ajouté
    reste invisible aux requêtes tant qu'il n'est pas envoyé. Le contrôle de
    doublon tient donc en deux temps — ce que la base porte déjà, et ce que ce
    lot vient d'ajouter — suivis d'un envoi explicite.
    """
    vus_dans_ce_lot: set[tuple] = set()

    for releve in releves:
        match = session.execute(
            select(Match).where(
                Match.provider == FOURNISSEUR,
                Match.provider_match_id == releve.provider_match_id,
            )
        ).scalar_one_or_none()
        if match is None:
            rapport.ignores.append(
                {"motif": "cote sans match en base", "fixture": releve.provider_match_id}
            )
            continue

        cle = (match.id, releve.bookmaker, releve.marche, releve.selection, releve.releve_le)
        if cle in vus_dans_ce_lot:
            rapport.cotes_deja_presentes += 1
            continue

        deja = (
            session.execute(
                select(OddsSnapshot).where(
                    OddsSnapshot.match_id == match.id,
                    OddsSnapshot.bookmaker == releve.bookmaker,
                    OddsSnapshot.market == releve.marche,
                    OddsSnapshot.selection == releve.selection,
                    OddsSnapshot.captured_at == releve.releve_le,
                )
            )
            .scalars()
            .first()
        )
        if deja is not None:
            rapport.cotes_deja_presentes += 1
            continue

        session.add(
            OddsSnapshot(
                match_id=match.id,
                bookmaker=releve.bookmaker,
                market=releve.marche,
                selection=releve.selection,
                odds=releve.cote,
                captured_at=releve.releve_le,
                is_closing=releve.cloture,
                source=FOURNISSEUR,
            )
        )
        vus_dans_ce_lot.add(cle)
        rapport.cotes_inserees += 1

    session.flush()


async def importer_cotes(
    session,
    client,
    dates: list[str],
    rapport: Rapport | None = None,
    dry_run: bool = False,
) -> Rapport:
    """Importer les cotes des matchs d'une liste de dates.

    Interroger par date plutôt que par match coûte une poignée d'appels au lieu
    d'un par rencontre — le quota est large, mais le réseau ne l'est pas.
    """
    rapport = rapport or Rapport()
    ligues_du_perimetre = {identifiant for identifiant, _, _ in LIGUES.values()}

    for date in dates:
        page, pages = 1, 1
        while page <= pages:
            reponse = await appeler(client, "odds", {"date": date, "page": page}, rapport)
            if reponse is None:
                break
            pages = (reponse.get("paging") or {}).get("total", 1)
            entrees = [
                entree
                for entree in (reponse.get("response") or [])
                if (entree.get("league") or {}).get("id") in ligues_du_perimetre
            ]
            for entree in entrees:
                releves = parser_cotes(entree)
                if not dry_run:
                    _ecrire_cotes(session, releves, rapport)
            logger.info(f"{date} page {page}/{pages} : {len(entrees)} matchs du périmètre")
            page += 1
        if not dry_run:
            session.commit()

    return rapport


# ──────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────


def ecrire_rapport(rapport: Rapport, repertoire: str = "rapports") -> Path:
    chemin = Path(repertoire)
    chemin.mkdir(parents=True, exist_ok=True)
    fichier = chemin / f"import_api_football_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    fichier.write_text(
        json.dumps(rapport.en_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return fichier


async def _executer(args) -> Rapport:
    client = ClientApiFootball()
    rapport = Rapport()
    with SessionLocal() as session:
        if args.matchs:
            await importer_matchs(
                session, client, args.saison, args.competitions, rapport, args.dry_run
            )
        if args.cotes:
            aujourdhui = datetime.now(UTC).date()
            dates = [(aujourdhui + timedelta(days=n)).isoformat() for n in range(args.jours)]
            await importer_cotes(session, client, dates, rapport, args.dry_run)
    return rapport


def main() -> None:
    parser = argparse.ArgumentParser(description="Import API-Football")
    parser.add_argument(
        "--matchs", action="store_true", help="Importer le calendrier et les résultats"
    )
    parser.add_argument(
        "--cotes", action="store_true", help="Importer les cotes des matchs à venir"
    )
    parser.add_argument(
        "--saison", type=int, default=None, help="Saison API (défaut : la courante)"
    )
    parser.add_argument(
        "--competition", action="append", dest="competitions", help="Code Football-Data ; répétable"
    )
    parser.add_argument(
        "--jours", type=int, default=3, help="Fenêtre de cotes, en jours (défaut : 3)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Lire sans rien écrire")
    args = parser.parse_args()

    if not (args.matchs or args.cotes):
        parser.error("Rien à faire : précisez --matchs et/ou --cotes.")
    if args.saison is None:
        maintenant = datetime.now(UTC)
        args.saison = maintenant.year if maintenant.month >= 7 else maintenant.year - 1

    logger.info(
        f"=== Import API-Football — saison {args.saison} "
        f"({saison_football_data(args.saison)}){' — à blanc' if args.dry_run else ''} ==="
    )
    rapport = asyncio.run(_executer(args))
    logger.info(
        f"{rapport.matchs_crees} matchs créés, {rapport.matchs_mis_a_jour} mis à jour, "
        f"{rapport.matchs_inchanges} inchangés | {rapport.cotes_inserees} cotes insérées, "
        f"{rapport.cotes_deja_presentes} déjà présentes | {rapport.appels} appels"
    )
    if rapport.equipes_creees:
        logger.warning(f"Équipes créées, sans historique : {', '.join(rapport.equipes_creees)}")
    if rapport.ignores:
        logger.warning(f"{len(rapport.ignores)} anomalies — voir le rapport")
    if not args.dry_run:
        logger.info(f"Rapport écrit : {ecrire_rapport(rapport)}")


if __name__ == "__main__":
    main()
