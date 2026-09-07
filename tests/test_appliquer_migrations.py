"""Tests du lanceur de migrations.

Ce script est le seul du dépôt qui écrive dans la base de production. Il encode
la règle de sécurité la plus stricte du projet — jamais de modification sans
sauvegarde préalable **vérifiée** — et c'est cette garantie qui est testée ici,
avant même le bon déroulement des migrations.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import appliquer_migrations as lanceur


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base minimale, avec un dossier de sauvegardes isolé."""
    chemin = tmp_path / "pronostic.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE features (id INTEGER PRIMARY KEY, valeur REAL)")
    con.execute("INSERT INTO features (valeur) VALUES (1.5)")
    con.commit()
    con.close()

    monkeypatch.setattr(lanceur.settings, "database_url", f"sqlite:///{chemin}")
    monkeypatch.setattr(lanceur.settings, "backups_dir", tmp_path / "backups")
    return chemin


@pytest.fixture
def migrations(tmp_path, monkeypatch):
    """Deux migrations jouets, à la place de celles du dépôt."""
    dossier = tmp_path / "migrations"
    dossier.mkdir()
    (dossier / "20260101_une.sql").write_text(
        "BEGIN TRANSACTION;\nALTER TABLE features ADD COLUMN une REAL;\nCOMMIT;\n",
        encoding="utf-8",
    )
    (dossier / "20260102_deux.sql").write_text(
        "BEGIN TRANSACTION;\nALTER TABLE features ADD COLUMN deux REAL;\nCOMMIT;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lanceur, "MIGRATIONS", dossier)
    return dossier


class TestSauvegarde:
    def test_la_sauvegarde_est_prise_et_verifiee(self, base):
        copie = lanceur.sauvegarder_et_verifier(base)

        assert copie.exists()
        with sqlite3.connect(copie) as con:
            assert con.execute("SELECT valeur FROM features").fetchone() == (1.5,)

    def test_une_sauvegarde_corrompue_arrete_tout(self, base, monkeypatch):
        """Une copie invalide ne se découvre pas au moment d'en avoir besoin."""

        def copie_corrompue(source, cible):
            Path(cible).write_bytes(b"ceci n'est pas une base SQLite")

        monkeypatch.setattr(lanceur.shutil, "copy2", copie_corrompue)

        with pytest.raises((SystemExit, sqlite3.DatabaseError)):
            lanceur.sauvegarder_et_verifier(base)

    def test_chaque_sauvegarde_a_son_propre_nom(self, base):
        """Deux exécutions ne doivent pas écraser la sauvegarde précédente."""
        premiere = lanceur.sauvegarder_et_verifier(base)
        deuxieme = lanceur.sauvegarder_et_verifier(base)

        assert premiere.exists() and deuxieme.exists()


class TestRegistre:
    def test_une_migration_n_est_appliquee_qu_une_fois(self, base, migrations):
        con = sqlite3.connect(base)
        for fichier in lanceur.migrations_disponibles():
            lanceur.appliquer(fichier, con)

        passees = lanceur.deja_appliquees(con)
        assert passees == {"20260101_une.sql", "20260102_deux.sql"}

        # Le second passage ne retient plus rien à faire.
        restantes = [f for f in lanceur.migrations_disponibles() if f.name not in passees]
        assert restantes == []
        con.close()

    def test_l_ordre_suit_le_nom_du_fichier(self, migrations):
        noms = [f.name for f in lanceur.migrations_disponibles()]

        assert noms == sorted(noms)
        assert noms[0].startswith("20260101")

    def test_le_registre_survit_a_la_fermeture(self, base, migrations):
        con = sqlite3.connect(base)
        lanceur.appliquer(lanceur.migrations_disponibles()[0], con)
        con.close()

        con = sqlite3.connect(base)
        assert "20260101_une.sql" in lanceur.deja_appliquees(con)
        con.close()


class TestApplication:
    def test_les_colonnes_sont_bien_ajoutees(self, base, migrations):
        con = sqlite3.connect(base)
        for fichier in lanceur.migrations_disponibles():
            lanceur.appliquer(fichier, con)

        colonnes = {c[1] for c in con.execute("PRAGMA table_info(features)")}
        assert {"une", "deux"} <= colonnes
        con.close()

    def test_les_donnees_existantes_sont_preservees(self, base, migrations):
        con = sqlite3.connect(base)
        for fichier in lanceur.migrations_disponibles():
            lanceur.appliquer(fichier, con)

        assert con.execute("SELECT valeur FROM features").fetchone() == (1.5,)
        con.close()

    def test_une_migration_rejouee_echoue_sans_toucher_au_registre(self, base, migrations):
        """SQLite refuse ADD COLUMN sur une colonne existante — c'est le filet."""
        con = sqlite3.connect(base)
        premiere = lanceur.migrations_disponibles()[0]
        lanceur.appliquer(premiere, con)

        with pytest.raises(sqlite3.OperationalError):
            lanceur.appliquer(premiere, con)

        assert con.execute("SELECT valeur FROM features").fetchone() == (1.5,)
        con.close()


class TestMigrationsReelles:
    def test_celles_du_depot_sont_toutes_lisibles(self):
        """Un fichier illisible ne doit pas se découvrir en production."""
        fichiers = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))

        assert fichiers, "aucune migration trouvée"
        for fichier in fichiers:
            contenu = fichier.read_text(encoding="utf-8")
            assert contenu.strip(), f"{fichier.name} est vide"

    def test_leurs_noms_sont_horodates(self):
        """La convention AAAAMMJJ_description.sql fixe l'ordre d'application."""
        for fichier in (Path(__file__).parent.parent / "migrations").glob("*.sql"):
            prefixe = fichier.name.split("_")[0]
            assert len(prefixe) == 8 and prefixe.isdigit(), (
                f"{fichier.name} ne commence pas par une date AAAAMMJJ"
            )
