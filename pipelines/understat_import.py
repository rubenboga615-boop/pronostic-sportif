"""Import des xG Understat vers `xg_match_stats`.

Ce pipeline **rattache**, il ne crée pas de matchs. C'est délibéré : un match
Understat n'a ni cotes, ni buts de mi-temps, ni arbitre. L'insérer produirait
une ligne que le pipeline de features ne saurait pas décrire et sur laquelle
aucun edge ne serait calculable — un trou silencieux dans le corpus, plutôt
qu'un manque visible.

Les matchs viennent donc de Football-Data, et Understat ne fait qu'ajouter les
trois colonnes que personne d'autre ne fournit. Les lignes sans contrepartie en
base sont comptées et rapportées, jamais insérées de force.

Idempotence
-----------
Une seconde exécution ne crée aucun doublon : chaque (match, équipe) est mis à
jour s'il existe déjà. Sans cela, relancer l'import après un ajout de matchs
doublerait les xG de tout l'historique déjà traité.

Contrôle de cohérence
---------------------
Le score d'Understat est comparé à celui de la base. Un désaccord signale un
mauvais rattachement — deux clubs distincts confondus, ou un décalage de date —
et la ligne est refusée. C'est le seul garde-fou qui attrape une correspondance
d'équipe fausse mais plausible ; sans lui, l'erreur s'écrirait en silence.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import func

from app.database import SessionLocal
from app.models import Match, Team, XgMatchStats
from collectors.understat.game_stats import SOURCE, LigneXg, lire_game_stats


def _index_des_equipes(session) -> dict[str, int]:
    """Nom canonique -> identifiant, pour éviter une requête par ligne."""
    return {nom: identifiant for identifiant, nom in session.query(Team.id, Team.canonical_name)}


def _index_des_matchs(session) -> dict[tuple[int, date, bool], int]:
    """(équipe, jour, domicile) -> identifiant du match.

    Construit en un seul balayage. Une équipe ne jouant qu'un match par jour,
    la clé est unique — c'est ce qui rend le rattachement possible sans
    identifiant de match côté Understat.
    """
    index: dict[tuple[int, date, bool], int] = {}
    for identifiant, jour, domicile_id, exterieur_id in session.query(
        Match.id, Match.match_date, Match.home_team_id, Match.away_team_id
    ):
        if jour is None:
            continue
        jour = jour.date() if isinstance(jour, datetime) else jour
        index[(domicile_id, jour, True)] = identifiant
        index[(exterieur_id, jour, False)] = identifiant
    return index


def _scores_des_matchs(session) -> dict[int, tuple[int | None, int | None]]:
    """Identifiant -> (buts domicile, buts extérieur), pour le contrôle."""
    return {
        identifiant: (domicile, exterieur)
        for identifiant, domicile, exterieur in session.query(
            Match.id, Match.home_goals, Match.away_goals
        )
    }


def _score_concorde(ligne: LigneXg, score: tuple[int | None, int | None]) -> bool:
    """Le score d'Understat est-il celui du match retrouvé ?

    Un score absent d'un côté ou de l'autre ne prouve rien : on laisse passer.
    Seul un désaccord franc est retenu comme erreur.
    """
    buts_domicile, buts_exterieur = score
    if buts_domicile is None or buts_exterieur is None:
        return True
    if ligne.buts_marques is None or ligne.buts_encaisses is None:
        return True

    attendus = (
        (buts_domicile, buts_exterieur) if ligne.domicile else (buts_exterieur, buts_domicile)
    )
    return (ligne.buts_marques, ligne.buts_encaisses) == attendus


def importer_xg(
    chemin: Path,
    *,
    ligues: list[str] | None = None,
    simuler: bool = False,
) -> dict:
    """Charger les xG d'un export Understat dans `xg_match_stats`.

    Args:
        chemin: export Understat (``game_stats.csv``).
        ligues: codes Football-Data à traiter (défaut : les cinq du projet).
        simuler: tout calculer et ne rien écrire. À utiliser d'abord : le
            rapport dit alors exactement ce qu'un import réel ferait.

    Returns:
        Rapport d'import. Invariant vérifiable :
        ``lignes_retenues == inserees + mises_a_jour + sans_match
        + equipes_inconnues + scores_discordants``.
    """
    lignes, lecture = lire_game_stats(Path(chemin), ligues=ligues)

    rapport = {
        "demarre_a": datetime.now(UTC).isoformat(),
        "fichier": str(chemin),
        "simule": simuler,
        "lignes_retenues": len(lignes),
        "inserees": 0,
        "mises_a_jour": 0,
        "sans_match": 0,
        "equipes_inconnues": 0,
        "scores_discordants": 0,
        "lecture": lecture,
        "equipes_absentes_de_la_base": [],
        "exemples_discordance": [],
    }

    session = SessionLocal()
    try:
        equipes = _index_des_equipes(session)
        matchs = _index_des_matchs(session)
        scores = _scores_des_matchs(session)

        existantes = {
            (match_id, team_id): identifiant
            for identifiant, match_id, team_id in session.query(
                XgMatchStats.id, XgMatchStats.match_id, XgMatchStats.team_id
            ).filter(XgMatchStats.source == SOURCE)
        }

        absentes: set[str] = set()
        for ligne in lignes:
            equipe_id = equipes.get(ligne.equipe)
            if equipe_id is None:
                # L'équipe existe chez Understat mais pas en base : ses matchs
                # n'ont simplement pas encore été importés.
                rapport["equipes_inconnues"] += 1
                absentes.add(ligne.equipe)
                continue

            match_id = matchs.get((equipe_id, ligne.jour, ligne.domicile))
            if match_id is None:
                rapport["sans_match"] += 1
                continue

            if not _score_concorde(ligne, scores.get(match_id, (None, None))):
                rapport["scores_discordants"] += 1
                if len(rapport["exemples_discordance"]) < 5:
                    rapport["exemples_discordance"].append(
                        f"{ligne.equipe} {ligne.jour} : Understat "
                        f"{ligne.buts_marques}-{ligne.buts_encaisses}, "
                        f"base {scores.get(match_id)}"
                    )
                continue

            valeurs = {
                "xg": ligne.xg,
                "xga": ligne.xga,
                "npxg": ligne.npxg,
                "source": SOURCE,
                "retrieved_at": datetime.now(UTC),
                "quality_status": "ok",
            }

            identifiant = existantes.get((match_id, equipe_id))
            if identifiant is not None:
                rapport["mises_a_jour"] += 1
                if not simuler:
                    session.query(XgMatchStats).filter(XgMatchStats.id == identifiant).update(
                        valeurs
                    )
            else:
                rapport["inserees"] += 1
                if not simuler:
                    session.add(XgMatchStats(match_id=match_id, team_id=equipe_id, **valeurs))
                    # Éviter d'insérer deux fois la même paire dans un même
                    # passage, si l'export contenait un doublon.
                    existantes[(match_id, equipe_id)] = -1

        if simuler:
            session.rollback()
        else:
            session.commit()

        rapport["equipes_absentes_de_la_base"] = sorted(absentes)
        rapport["total_en_base"] = (
            session.query(func.count(XgMatchStats.id))
            .filter(XgMatchStats.source == SOURCE)
            .scalar()
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    rapport["termine_a"] = datetime.now(UTC).isoformat()
    logger.info(
        f"{'Simulation' if simuler else 'Import'} Understat — "
        f"{rapport['inserees']} insérées, {rapport['mises_a_jour']} mises à jour, "
        f"{rapport['sans_match']} sans match en base, "
        f"{rapport['equipes_inconnues']} sur des équipes absentes, "
        f"{rapport['scores_discordants']} refusées pour score discordant"
    )
    return rapport


__all__ = ["importer_xg"]
