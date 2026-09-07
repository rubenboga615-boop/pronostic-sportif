#!/usr/bin/env python3
"""Proposer les correspondances d'équipes d'un fournisseur, à relire.

Ce script **ne décide rien**. Il range les noms d'un fournisseur en quatre tas
et écrit une proposition. Vous la relisez, corrigez ce qui doit l'être, puis
fusionnez dans `collectors/mapping/equipes.json` — qui est commité, et fait
alors autorité.

Pourquoi cette étape manuelle : « Wolves » et « Wolverhampton Wanderers »
désignent le même club sans se ressembler, « Real Sociedad » et « Real Madrid »
se ressemblent sans avoir de rapport. Aucun seuil ne sépare ces deux cas. Une
seule confusion contamine des années d'historique sans lever d'erreur.

Usage :
    # 1. Récupérer les noms du fournisseur (sortie de la sonde, ou à la main)
    python scripts/generer_correspondances.py \\
        --fournisseur api_football --ligue E0 --noms data/raw/noms_e0.json

    # 2. Relire proposition_api_football_E0.json, corriger, puis fusionner
    python scripts/generer_correspondances.py --fusionner proposition_*.json

Le fichier de noms est une liste JSON de chaînes, ou un objet ``{"noms": [...]}``.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from collectors.mapping.candidats import proposer, resume
from collectors.mapping.registre import (
    FICHIER_PAR_DEFAUT,
    FOURNISSEURS,
    charger_registre,
)


def _lire_noms(chemin: Path) -> list[str]:
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    if isinstance(donnees, dict):
        donnees = donnees.get("noms", [])
    if not isinstance(donnees, list):
        raise ValueError(f"{chemin} : attendu une liste de noms, ou {{'noms': [...]}}")
    return [str(n) for n in donnees]


def generer(fournisseur: str, ligue: str, chemin_noms: Path, sortie: Path | None) -> Path:
    """Écrire la proposition, et l'afficher au passage."""
    noms = _lire_noms(chemin_noms)
    registre = charger_registre()
    propositions = proposer(fournisseur, ligue, noms, registre=registre)

    comptes = resume(propositions)
    logger.info(
        f"{len(noms)} noms — {comptes['resolu']} déjà résolus, "
        f"{comptes['candidat']} candidats à confirmer, "
        f"{comptes['ambigu']} ambigus, {comptes['aucun']} sans correspondance"
    )

    a_relire = [p for p in propositions if p.decision != "resolu"]
    for p in a_relire:
        autres = (
            "  (autres : " + ", ".join(f"{c} {s}" for c, s in p.autres) + ")" if p.autres else ""
        )
        print(f"  [{p.decision:8s}] {p.nom:32s} -> {p.canonique or '?':32s} {p.score}{autres}")

    sortie = sortie or Path(f"proposition_{fournisseur}_{ligue}.json")
    sortie.write_text(
        json.dumps(
            {
                "_relecture": (
                    "Vérifiez chaque ligne. Corrigez 'canonique', supprimez ce qui "
                    "ne doit pas être ajouté, puis lancez --fusionner."
                ),
                "fournisseur": fournisseur,
                "ligue": ligue,
                "correspondances": {
                    p.nom: p.canonique for p in a_relire if p.canonique is not None
                },
                "sans_correspondance": [p.nom for p in a_relire if p.canonique is None],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    logger.info(f"Proposition écrite : {sortie}")
    return sortie


def fusionner(fichiers: list[Path]) -> None:
    """Intégrer des propositions relues dans le registre commité."""
    registre = charger_registre()
    ajouts = 0

    for fichier in fichiers:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
        fournisseur, ligue = donnees["fournisseur"], donnees["ligue"]
        if fournisseur not in FOURNISSEURS:
            raise ValueError(f"{fichier} : fournisseur inconnu {fournisseur!r}")

        table = registre.correspondances.setdefault(fournisseur, {}).setdefault(ligue, {})
        for nom, canonique in donnees.get("correspondances", {}).items():
            if canonique is None:
                continue
            if table.get(nom) not in (None, canonique):
                raise ValueError(
                    f"{fichier} : {nom!r} pointait déjà vers {table[nom]!r}, "
                    f"et voudrait pointer vers {canonique!r}. Tranchez à la main."
                )
            table[nom] = canonique
            ajouts += 1

    anomalies = registre.verifier()
    if anomalies:
        raise ValueError("Fusion refusée, registre incohérent :\n  " + "\n  ".join(anomalies))

    FICHIER_PAR_DEFAUT.write_text(
        json.dumps(
            {"correspondances": registre.correspondances},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    logger.info(f"{ajouts} correspondances fusionnées dans {FICHIER_PAR_DEFAUT}")
    logger.info("Relisez le diff, puis commitez : c'est cette décision qui fait autorité.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fournisseur", choices=FOURNISSEURS)
    parser.add_argument("--ligue", help="Code Football-Data : E0, SP1, I1, D1, F1")
    parser.add_argument("--noms", type=Path, help="Fichier JSON des noms du fournisseur")
    parser.add_argument("--sortie", type=Path, help="Où écrire la proposition")
    parser.add_argument(
        "--fusionner",
        nargs="+",
        type=Path,
        metavar="PROPOSITION",
        help="Intégrer des propositions relues dans le registre",
    )
    args = parser.parse_args()

    if args.fusionner:
        fusionner(args.fusionner)
        return

    if not (args.fournisseur and args.ligue and args.noms):
        parser.error("--fournisseur, --ligue et --noms sont requis (ou --fusionner)")

    generer(args.fournisseur, args.ligue, args.noms, args.sortie)


if __name__ == "__main__":
    main()
