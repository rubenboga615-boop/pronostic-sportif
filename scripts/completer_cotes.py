#!/usr/bin/env python3
"""Ajouter aux matchs déjà en base les cotes que leurs fichiers portent.

Quand le parseur apprend à lire de nouvelles colonnes, les matchs importés
avant ne les reçoivent jamais : `historical_import` classe un match existant
en « doublon » et abandonne sa ligne, cotes comprises. C'est le bon
comportement — il garantit qu'aucun réimport ne duplique quoi que ce soit —
mais il laisse un angle mort, et ce script est la porte de sortie.

Le cas s'est produit deux fois :

- le 08/09/2026, quand les cotes Over/Under 2,5 sont devenues lisibles ;
- le 22/09/2026, quand les colonnes Betbrain (`BbMx`/`BbAv`, l'ancien nom des
  agrégats) et les agrégats de clôture (`MaxC`, `AvgC`) l'ont été à leur tour.

Ce second cas touche 20 034 matchs sans aucune cote Over/Under, et la totalité
du corpus valorisé à une cote inférieure de 1,9 à 3,6 % à la meilleure du
marché.

Le script ne crée ni match, ni équipe, ni saison : un match introuvable est
compté et signalé, jamais inventé. Sa place est dans `import_historical_data`.

⚠️ SAUVEGARDE PRÉALABLE. Le script écrit dans la base de production.
    python scripts/appliquer_migrations.py --etat   # vérifie l'accès
    cp data/pronostic.db data/backups/avant_completion.db

Usage :
    python scripts/completer_cotes.py --simuler          # ne rien écrire
    python scripts/completer_cotes.py                    # les 5 championnats
    python scripts/completer_cotes.py --leagues E0 SP1
    python scripts/completer_cotes.py --racine chemin/vers/les/csv
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from collectors.football_data.league_config import LEAGUE_CONFIG, get_league_name
from pipelines.completer_cotes import completer_cotes

# Deux arborescences coexistent, selon l'outil qui a téléchargé :
#
#   data/raw/football_data/<CODE>/<CODE>_<SAISON>.csv   ← téléchargeur du projet
#   data/raw/football-data/<SAISON>/<CODE>.csv          ← scripts de récupération
#
# Le tiret bas et le tiret haut se ressemblent assez pour qu'on s'y trompe, et
# assez peu pour que le dossier reste introuvable. Le script essaie donc les
# deux plutôt que d'exiger qu'on sache laquelle on a.
RACINES_CANDIDATES: tuple[Path, ...] = (
    Path("data/raw/football_data"),
    Path("data/raw/football-data"),
)


def fichiers_du_championnat(racine: Path, code: str) -> list[Path]:
    """CSV d'un championnat, toutes saisons, triés chronologiquement.

    Deux arborescences coexistent selon l'outil qui a téléchargé :
    ``<racine>/<saison>/<code>.csv`` et ``<racine>/<code>/<code>_<saison>.csv``.
    Les deux sont acceptées — refuser l'une des deux n'apporterait rien.
    """
    par_saison = sorted(racine.glob(f"*/{code}.csv"))
    par_code = sorted(racine.glob(f"{code}/{code}_*.csv"))
    return par_saison or par_code


def trouver_racine(explicite: Path | None) -> Path:
    """Dossier des CSV : celui demandé, ou la première arborescence trouvée.

    Une racine explicite est utilisée telle quelle, même vide — l'utilisateur
    sait ce qu'il fait, et un repli silencieux masquerait sa faute de frappe.

    Raises:
        SystemExit: aucune arborescence trouvée. Le message dit ce qui a été
            cherché et ce que `data/raw/` contient réellement : une erreur qui
            n'indique pas la sortie oblige à relire le code.
    """
    if explicite is not None:
        if not explicite.exists():
            raise SystemExit(f"Dossier introuvable : {explicite.resolve()}")
        return explicite

    for candidate in RACINES_CANDIDATES:
        if candidate.exists() and any(candidate.rglob("*.csv")):
            logger.info(f"Arborescence trouvée : {candidate}")
            return candidate

    cherchees = "\n  ".join(str(c.resolve()) for c in RACINES_CANDIDATES)
    racine = Path("data/raw")
    if racine.exists():
        contenu = sorted(p.name for p in racine.iterdir())
        detail = f"`data/raw/` contient : {contenu or 'rien'}"
    else:
        detail = "`data/raw/` n'existe pas."
    raise SystemExit(
        f"Aucun CSV Football-Data trouvé. Cherché dans :\n  {cherchees}\n"
        f"{detail}\n"
        f"Indiquez le bon dossier avec --racine, ou lancez d'abord "
        f"scripts/import_historical_data.py pour télécharger les fichiers."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--leagues",
        nargs="+",
        default=sorted(LEAGUE_CONFIG),
        metavar="CODE",
        help=f"codes à traiter (défaut : {' '.join(sorted(LEAGUE_CONFIG))})",
    )
    parser.add_argument(
        "--racine",
        type=Path,
        default=None,
        help="dossier des CSV (détecté automatiquement si omis)",
    )
    parser.add_argument(
        "--simuler",
        action="store_true",
        help="tout calculer et tout rapporter, sans écrire une seule ligne",
    )
    args = parser.parse_args()

    inconnus = [c for c in args.leagues if c not in LEAGUE_CONFIG]
    if inconnus:
        raise SystemExit(
            f"Championnats hors périmètre : {inconnus}. Attendu : {sorted(LEAGUE_CONFIG)}"
        )

    racine = trouver_racine(args.racine)

    if args.simuler:
        logger.info("SIMULATION — aucune écriture ne sera faite")

    totaux = {"ajoutees": 0, "deja": 0, "introuvables": 0, "fichiers": 0}
    for code in args.leagues:
        fichiers = fichiers_du_championnat(racine, code)
        if not fichiers:
            logger.warning(f"{code} : aucun fichier sous {racine}")
            continue

        logger.info(f"=== {code} — {get_league_name(code)} — {len(fichiers)} fichiers ===")
        rapport = completer_cotes(fichiers, code, simuler=args.simuler)

        totaux["ajoutees"] += rapport["cotes_ajoutees"]
        totaux["deja"] += rapport["cotes_deja_presentes"]
        totaux["introuvables"] += rapport["matchs_introuvables"]
        totaux["fichiers"] += rapport["fichiers"]

        if rapport["matchs_introuvables"]:
            logger.warning(
                f"{code} : {rapport['matchs_introuvables']} matchs des fichiers ne sont "
                f"pas en base. Ils ne sont pas créés ici — lancez "
                f"scripts/import_historical_data.py si vous les voulez."
            )

    logger.info("=" * 56)
    logger.info(
        f"{totaux['fichiers']} fichiers | "
        f"{totaux['ajoutees']:,} cotes ajoutées | "
        f"{totaux['deja']:,} déjà présentes | "
        f"{totaux['introuvables']:,} matchs introuvables"
    )
    if args.simuler:
        logger.info("Simulation : rien n'a été écrit. Relancez sans --simuler.")
    elif totaux["ajoutees"]:
        logger.info("Étape suivante : rejouer la valorisation et le backtest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
