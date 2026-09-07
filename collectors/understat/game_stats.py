"""Lecture d'un export Understat par match et par équipe.

Understat publie, pour chaque match, une ligne par équipe : ses xG, ceux
concédés, le npxG, le ppda, les passes profondes. C'est la seule source du
projet pour les trois colonnes `xg_avg_5`, `xga_avg_5` et `npxg_avg_5`, vides
depuis le premier jour.

Ce module **lit et résout**, il n'écrit pas en base : l'écriture est le travail
de :mod:`pipelines.understat_import`. La séparation permet de vérifier ce qui
sera importé avant de l'importer.

Comment un match est retrouvé
-----------------------------
L'export ne porte **aucun identifiant de match** — seulement le club, la date
et le camp. Apparier les deux moitiés d'un match par (ligue, date) est
impossible : lors d'une dernière journée, dix matchs partagent la même heure au
horaire près, et les scores ne suffisent pas non plus à les départager (deux
victoires 2-1 le même après-midi sont courantes).

Cet appariement n'est heureusement pas nécessaire. `xg_match_stats` s'indexe
par (match, équipe), et **une équipe ne joue qu'un match par jour** — vérifié
sur les 41 722 lignes de l'export, sans une seule exception. Chaque ligne est
donc rattachée indépendamment, par (club, jour, camp), et l'ambiguïté ne se
pose jamais.

Les noms d'équipes passent par le registre de correspondances, en résolution
stricte : un nom inconnu lève plutôt que de créer une équipe fantôme (voir
:mod:`collectors.mapping.registre`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from collectors.mapping.registre import (
    NomInconnuError,
    RegistreCorrespondances,
    charger_registre,
)

# Nom de ligue Understat -> code Football-Data. La RFPL (championnat russe)
# est délibérément absente : elle ne fait pas partie des cinq championnats du
# projet, et ses matchs n'ont aucune contrepartie en base.
LIGUES = {
    "EPL": "E0",
    "La liga": "SP1",
    "Serie A": "I1",
    "Bundesliga": "D1",
    "Ligue 1": "F1",
}

SOURCE = "understat"


@dataclass(frozen=True)
class LigneXg:
    """Les statistiques avancées d'une équipe sur un match.

    `equipe` est déjà le nom **canonique** : la résolution a eu lieu à la
    lecture, pour qu'aucun nom de fournisseur ne circule plus loin.
    """

    ligue: str  # code Football-Data : E0, SP1, I1, D1, F1
    jour: date
    equipe: str  # nom canonique
    domicile: bool
    xg: float | None
    xga: float | None
    npxg: float | None
    buts_marques: int | None
    buts_encaisses: int | None


class ExportIllisibleError(ValueError):
    """L'export ne porte pas les colonnes attendues.

    Levée à la lecture plutôt qu'au premier accès manquant : un export dont le
    format a changé doit être signalé d'un coup, pas ligne par ligne.
    """


COLONNES_ATTENDUES = frozenset(
    {"league", "date", "club_name", "home_away", "xG", "xGA", "npxG", "scored", "missed"}
)


def _flottant(valeur: str | None) -> float | None:
    if valeur is None or valeur.strip() == "":
        return None
    try:
        return float(valeur)
    except ValueError:
        return None


def _entier(valeur: str | None) -> int | None:
    flottant = _flottant(valeur)
    return None if flottant is None else int(flottant)


def _jour(valeur: str) -> date | None:
    """Date seule : l'heure d'Understat et celle de Football-Data diffèrent.

    Football-Data ne publie pas d'heure de coup d'envoi — les matchs sont en
    base à minuit. Comparer les horodatages complets ne rattacherait donc
    jamais rien.
    """
    for format_ in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(valeur.strip(), format_).date()
        except ValueError:
            continue
    return None


def lire_game_stats(
    chemin: Path,
    *,
    ligues: list[str] | None = None,
    registre: RegistreCorrespondances | None = None,
) -> tuple[list[LigneXg], dict]:
    """Lire l'export et résoudre les noms d'équipes.

    Args:
        chemin: fichier CSV de l'export Understat.
        ligues: codes Football-Data à retenir (défaut : les cinq du projet).
        registre: registre de correspondances ; chargé si absent.

    Returns:
        Les lignes exploitables, et un rapport de lecture. Le rapport compte ce
        qui a été écarté et pourquoi — une ligne muette est une ligne perdue.

    Raises:
        ExportIllisibleError: colonnes attendues absentes du fichier.
        NomInconnuError: une équipe n'a aucune correspondance connue. L'import
            s'arrête : mieux vaut refuser de démarrer que scinder l'historique
            d'un club en deux moitiés inutilisables.
    """
    registre = registre if registre is not None else charger_registre()
    retenues = set(ligues) if ligues else set(LIGUES.values())

    rapport = {
        "lignes_lues": 0,
        "lignes_retenues": 0,
        "ligues_ignorees": {},
        "dates_illisibles": 0,
    }
    lignes: list[LigneXg] = []

    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        lecteur = csv.DictReader(fichier)
        manquantes = COLONNES_ATTENDUES - set(lecteur.fieldnames or [])
        if manquantes:
            raise ExportIllisibleError(
                f"{chemin} : colonnes absentes {sorted(manquantes)}. "
                f"Trouvées : {sorted(lecteur.fieldnames or [])}"
            )

        for brute in lecteur:
            rapport["lignes_lues"] += 1

            code = LIGUES.get((brute.get("league") or "").strip())
            if code is None or code not in retenues:
                nom = (brute.get("league") or "?").strip()
                rapport["ligues_ignorees"][nom] = rapport["ligues_ignorees"].get(nom, 0) + 1
                continue

            jour = _jour(brute.get("date") or "")
            if jour is None:
                rapport["dates_illisibles"] += 1
                continue

            # Résolution stricte : lève sur un nom inconnu, jamais de
            # rapprochement approximatif.
            equipe = registre.canonique("understat", code, (brute.get("club_name") or "").strip())

            lignes.append(
                LigneXg(
                    ligue=code,
                    jour=jour,
                    equipe=equipe,
                    domicile=(brute.get("home_away") or "").strip() == "h",
                    xg=_flottant(brute.get("xG")),
                    xga=_flottant(brute.get("xGA")),
                    npxg=_flottant(brute.get("npxG")),
                    buts_marques=_entier(brute.get("scored")),
                    buts_encaisses=_entier(brute.get("missed")),
                )
            )
            rapport["lignes_retenues"] += 1

    logger.info(
        f"{chemin.name} : {rapport['lignes_retenues']} lignes retenues "
        f"sur {rapport['lignes_lues']} lues"
    )
    return lignes, rapport


def noms_non_resolus(chemin: Path, registre: RegistreCorrespondances | None = None) -> dict:
    """Les noms d'équipes qu'un import échouerait à résoudre, par ligue.

    À lancer **avant** l'import : il vaut mieux découvrir les vingt-cinq noms
    manquants d'un coup, et compléter le registre en une fois, que d'échouer
    vingt-cinq fois de suite.
    """
    registre = registre if registre is not None else charger_registre()
    par_ligue: dict[str, list[str]] = {}

    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        vus: set[tuple[str, str]] = set()
        for brute in csv.DictReader(fichier):
            code = LIGUES.get((brute.get("league") or "").strip())
            if code is None:
                continue
            nom = (brute.get("club_name") or "").strip()
            if (code, nom) in vus:
                continue
            vus.add((code, nom))
            if not registre.connait("understat", code, nom):
                par_ligue.setdefault(code, []).append(nom)

    return {code: sorted(noms) for code, noms in sorted(par_ligue.items())}


__all__ = [
    "LIGUES",
    "SOURCE",
    "ExportIllisibleError",
    "LigneXg",
    "NomInconnuError",
    "lire_game_stats",
    "noms_non_resolus",
]
