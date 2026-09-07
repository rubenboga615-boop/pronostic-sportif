#!/usr/bin/env python3
"""Appliquer les migrations SQL, dans l'ordre, une seule fois chacune.

Ce script encode la règle de sécurité la plus stricte du projet : **ne jamais
modifier la base sans sauvegarde préalable vérifiée**. Il refuse de partir sans
elle, et la vérifie lui-même — une sauvegarde qu'on n'a pas relue n'est pas une
sauvegarde, c'est un fichier.

Il tient aussi un registre des migrations déjà passées, dans une table
`schema_migrations`. Sans lui, il faut se souvenir de ce qu'on a lancé, et les
migrations SQLite ne sont pas rejouables : `ALTER TABLE ADD COLUMN` échoue sur
une colonne existante.

Usage :
    python scripts/appliquer_migrations.py --etat        # que reste-t-il ?
    python scripts/appliquer_migrations.py --simuler     # sans rien écrire
    python scripts/appliquer_migrations.py               # applique

La sauvegarde est prise automatiquement, vérifiée, et son chemin affiché avant
toute écriture.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from app.config import settings

MIGRATIONS = Path(__file__).parent.parent / "migrations"

TABLE_REGISTRE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    nom        TEXT PRIMARY KEY,
    applique_a TEXT NOT NULL
)
"""


def chemin_base() -> Path:
    """Chemin du fichier SQLite, déduit de la configuration."""
    url = settings.database_url
    if not url.startswith("sqlite"):
        raise SystemExit(f"Ce script ne gère que SQLite. DATABASE_URL = {url!r}")
    return Path(url.split("///")[-1])


def migrations_disponibles() -> list[Path]:
    """Fichiers `.sql`, triés par nom — donc par date, vu la convention."""
    return sorted(MIGRATIONS.glob("*.sql"))


def deja_appliquees(con: sqlite3.Connection) -> set[str]:
    con.execute(TABLE_REGISTRE)
    con.commit()
    return {ligne[0] for ligne in con.execute("SELECT nom FROM schema_migrations")}


def sauvegarder_et_verifier(base: Path) -> Path:
    """Copier la base, puis vérifier la copie. Lever si elle est douteuse.

    La vérification n'est pas une formalité : une copie prise pendant une
    écriture peut être structurellement invalide, et on ne le découvrirait
    qu'au moment d'en avoir besoin.
    """
    dossier = Path(settings.backups_dir)
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    copie = dossier / f"{base.stem}_avant_migrations_{horodatage}.db"

    shutil.copy2(base, copie)

    with sqlite3.connect(copie) as con:
        integrite = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrite != "ok":
            raise SystemExit(
                f"Sauvegarde invalide ({integrite}). Aucune migration n'est appliquée.\n"
                f"Vérifiez la base source avant de recommencer."
            )
        tables = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]

    taille_ko = copie.stat().st_size // 1024
    logger.info(f"Sauvegarde vérifiée : {copie} ({taille_ko} Ko, {tables} tables)")
    return copie


def appliquer(fichier: Path, con: sqlite3.Connection) -> None:
    """Exécuter une migration et l'inscrire au registre, atomiquement.

    Le script SQL porte sa propre transaction ; l'inscription au registre suit
    immédiatement, dans la même connexion. Une migration appliquée mais non
    inscrite serait rejouée au prochain passage et échouerait.

    La table de registre est créée au besoin : la fonction ne suppose pas
    qu'un appelant l'ait fait avant elle.
    """
    con.execute(TABLE_REGISTRE)
    con.executescript(fichier.read_text(encoding="utf-8"))
    con.execute(
        "INSERT OR REPLACE INTO schema_migrations (nom, applique_a) VALUES (?, ?)",
        (fichier.name, datetime.now(UTC).isoformat()),
    )
    con.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--etat", action="store_true", help="Lister sans rien appliquer")
    parser.add_argument("--simuler", action="store_true", help="Tout vérifier, ne rien écrire")
    args = parser.parse_args()

    base = chemin_base()
    if not base.exists():
        raise SystemExit(f"Base introuvable : {base}")

    con = sqlite3.connect(base)
    passees = deja_appliquees(con)
    toutes = migrations_disponibles()
    restantes = [f for f in toutes if f.name not in passees]

    logger.info(f"Base : {base}")
    for fichier in toutes:
        marque = "✓ appliquée" if fichier.name in passees else "· à appliquer"
        logger.info(f"  {marque}  {fichier.name}")

    if not restantes:
        logger.info("Rien à faire : toutes les migrations sont passées.")
        return

    if args.etat:
        logger.info(f"{len(restantes)} migration(s) en attente.")
        return

    if args.simuler:
        logger.info(f"Simulation : {len(restantes)} migration(s) seraient appliquées.")
        for fichier in restantes:
            logger.info(f"  {fichier.name}")
        logger.info("Aucune écriture effectuée.")
        return

    con.close()
    copie = sauvegarder_et_verifier(base)

    con = sqlite3.connect(base)
    appliquees = []
    try:
        for fichier in restantes:
            logger.info(f"Application : {fichier.name}")
            appliquer(fichier, con)
            appliquees.append(fichier.name)
    except sqlite3.Error as erreur:
        logger.error(f"Échec sur {fichier.name} : {erreur}")
        logger.error(f"Migrations appliquées avant l'échec : {appliquees or 'aucune'}")
        logger.error(f"Pour revenir en arrière : cp {copie} {base}")
        raise SystemExit(1) from erreur
    finally:
        con.close()

    logger.info(f"{len(appliquees)} migration(s) appliquée(s).")
    logger.info("Étape suivante obligatoire : recalculer les features.")
    logger.info("    python -m pipelines.feature_pipeline")


if __name__ == "__main__":
    main()
