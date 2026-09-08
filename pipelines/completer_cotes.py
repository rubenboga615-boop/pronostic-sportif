"""Charger les cotes manquantes de matchs déjà en base.

Pourquoi ce module existe
-------------------------
`historical_import` insère les cotes au moment où il crée le match. Un match
déjà présent est classé « doublon » et sa ligne est abandonnée — cotes
comprises. C'est le bon comportement pour un réimport ordinaire, mais il laisse
un angle mort : quand le **parseur** gagne des colonnes après coup, les matchs
importés avant ne les recevront jamais.

Le cas s'est produit. Les saisons 2023/24 et 2024/25 ont été importées avant
que le parseur ne lise les cotes Over/Under 2,5 (étape 3 de la feuille de
route). Leurs fichiers contiennent ces vingt colonnes, le parseur sait les lire
depuis, et pourtant la base n'en portait aucune — ce qui rendait le rendement
inobservable sur le marché où le modèle est le plus fort.

Ce module ne crée ni match, ni équipe, ni saison. Il ajoute des cotes à des
matchs existants, et rien d'autre. Un match introuvable est signalé, jamais
créé : sa place est dans `historical_import`.

Idempotence
-----------
Une série déjà en base n'est pas réinsérée — la clé retenue est
(match, bookmaker, marché, sélection). Relancer le script ne crée donc aucun
doublon, ce qui compte d'autant plus que les cotes n'ont pas de contrainte
d'unicité au niveau du schéma.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import null

from app.database import SessionLocal
from app.models import Match, OddsSnapshot, Team
from collectors.football_data.parser import parse_csv
from collectors.football_data.team_normalizer import normalize_team_name
from pipelines.historical_import import SERIES_DE_COTES


def _index_des_matchs(session, league_code: str) -> dict[tuple[str, str, Any], int]:
    """(équipe domicile, équipe extérieur, jour) -> identifiant du match.

    Le jour suffit à identifier une rencontre : deux équipes ne se rencontrent
    pas deux fois le même jour.
    """
    index: dict[tuple[str, str, Any], int] = {}
    lignes = (
        session.query(Match.id, Match.match_date, Team.canonical_name, Match.away_team_id)
        .join(Team, Team.id == Match.home_team_id)
        .all()
    )
    noms = dict(session.query(Team.id, Team.canonical_name).all())
    for identifiant, jour, domicile, away_id in lignes:
        if jour is None:
            continue
        jour = jour.date() if isinstance(jour, datetime) else jour
        index[(domicile, noms.get(away_id), jour)] = identifiant
    return index


def _cotes_existantes(session) -> set[tuple[int, str, str, str]]:
    """Clés (match, bookmaker, marché, sélection) déjà en base."""
    return {
        (m, b, ma, s)
        for m, b, ma, s in session.query(
            OddsSnapshot.match_id,
            OddsSnapshot.bookmaker,
            OddsSnapshot.market,
            OddsSnapshot.selection,
        )
    }


def completer_cotes(
    fichiers: list[Path],
    league_code: str = "E0",
    *,
    simuler: bool = False,
) -> dict:
    """Ajouter aux matchs existants les cotes que leurs fichiers portent.

    Args:
        fichiers: CSV Football-Data à relire.
        league_code: code de la ligue, pour la normalisation des noms.
        simuler: tout calculer sans rien écrire.

    Returns:
        Rapport d'exécution. Les matchs introuvables sont comptés et non créés.
    """
    rapport = {
        "fichiers": len(fichiers),
        "lignes_lues": 0,
        "matchs_retrouves": 0,
        "matchs_introuvables": 0,
        "cotes_ajoutees": 0,
        "cotes_deja_presentes": 0,
        "simule": simuler,
        "par_marche": {},
    }

    session = SessionLocal()
    try:
        index = _index_des_matchs(session, league_code)
        existantes = _cotes_existantes(session)

        for fichier in fichiers:
            df = parse_csv(Path(fichier))
            for _, ligne in df.iterrows():
                rapport["lignes_lues"] += 1
                domicile = ligne.get("home_team")
                exterieur = ligne.get("away_team")
                jour = ligne.get("match_date")
                if pd.isna(domicile) or pd.isna(exterieur) or pd.isna(jour):
                    continue

                cle = (
                    normalize_team_name(str(domicile), league_code),
                    normalize_team_name(str(exterieur), league_code),
                    pd.Timestamp(jour).date(),
                )
                match_id = index.get(cle)
                if match_id is None:
                    rapport["matchs_introuvables"] += 1
                    continue
                rapport["matchs_retrouves"] += 1

                for serie in SERIES_DE_COTES:
                    bookmaker = str(serie["bookmaker"])
                    marche = str(serie["market"])
                    # Une série n'a de sens que complète : sans toutes ses
                    # sélections, la marge du bookmaker n'est pas calculable.
                    valeurs: dict[str, float] = {}
                    for selection, colonne in serie["selections"].items():
                        val = ligne.get(colonne)
                        if pd.notna(val) and val > 0:
                            valeurs[selection] = float(val)
                    if len(valeurs) != len(serie["selections"]):
                        continue

                    for selection, cote in valeurs.items():
                        if (match_id, bookmaker, marche, selection) in existantes:
                            rapport["cotes_deja_presentes"] += 1
                            continue
                        rapport["cotes_ajoutees"] += 1
                        rapport["par_marche"][marche] = rapport["par_marche"].get(marche, 0) + 1
                        existantes.add((match_id, bookmaker, marche, selection))
                        if not simuler:
                            session.add(
                                OddsSnapshot(
                                    match_id=match_id,
                                    bookmaker=bookmaker,
                                    market=marche,
                                    selection=selection,
                                    odds=cote,
                                    # Seule la clôture a un instant connu ; une
                                    # cote d'ouverture non datée ne doit pas
                                    # passer pour un relevé pré-match daté
                                    # (migration 20260906_purge_odds_movement).
                                    #
                                    # `null()` et non `None` : la colonne porte
                                    # un `default=maintenant_utc` que SQLAlchemy
                                    # appliquerait à la place d'un None.
                                    captured_at=(
                                        datetime.now(UTC) if serie["is_closing"] else null()
                                    ),
                                    is_closing=bool(serie["is_closing"]),
                                    source="football_data",
                                )
                            )

        if simuler:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(
        f"{'Simulation' if simuler else 'Complétion'} des cotes — "
        f"{rapport['cotes_ajoutees']} ajoutées, "
        f"{rapport['cotes_deja_presentes']} déjà présentes, "
        f"{rapport['matchs_introuvables']} matchs introuvables"
    )
    return rapport


__all__ = ["completer_cotes"]
