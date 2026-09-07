"""Une migration doit mener au schéma que l'ORM décrit.

Sans ce contrôle, deux vérités coexistent : le schéma que produit
`Base.metadata.create_all` sur une base neuve, et celui qu'obtient une base de
production migrée. Elles divergent au premier `ALTER TABLE` oublié, et l'écart
ne se voit qu'en production — sur la seule base qu'on ne peut pas recréer.
"""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.models import Base

MIGRATIONS = Path("migrations")

# Table `features` telle qu'elle existait avant la migration du 07/09/2026.
FEATURES_AVANT = """
CREATE TABLE features (
    id INTEGER PRIMARY KEY,
    match_id INTEGER,
    team_id INTEGER,
    calculated_at TEXT,
    form_points_5 REAL,
    form_points_10 REAL,
    goals_for_avg_5 REAL,
    goals_against_avg_5 REAL,
    home_away_goals_for_avg REAL,
    home_away_goals_against_avg REAL,
    xg_avg_5 REAL,
    xga_avg_5 REAL,
    npxg_avg_5 REAL,
    shots_avg_5 REAL,
    shots_on_target_avg_5 REAL,
    league_position INTEGER,
    goal_difference INTEGER,
    elo_rating REAL,
    opponent_strength REAL,
    rest_days INTEGER,
    injury_impact REAL,
    odds_movement REAL,
    data_completeness REAL
)
"""


def _colonnes_orm(table: str) -> set[str]:
    moteur = create_engine("sqlite://")
    Base.metadata.create_all(moteur)
    return {c["name"] for c in inspect(moteur).get_columns(table)}


class TestMigrationMiTemps:
    FICHIER = MIGRATIONS / "20260907_add_half_time_features.sql"

    @pytest.fixture
    def base_avant(self, tmp_path):
        """Base au schéma antérieur, avec une ligne à préserver."""
        chemin = tmp_path / "avant.db"
        con = sqlite3.connect(chemin)
        con.executescript(FEATURES_AVANT)
        con.execute("INSERT INTO features (match_id, team_id, form_points_5) VALUES (1, 1, 9)")
        con.commit()
        yield con
        con.close()

    def test_la_migration_mene_au_schema_de_l_orm(self, base_avant):
        """Après migration, `features` porte exactement les colonnes du modèle."""
        base_avant.executescript(self.FICHIER.read_text(encoding="utf-8"))

        migrees = {c[1] for c in base_avant.execute("PRAGMA table_info(features)")}

        manquantes = _colonnes_orm("features") - migrees
        assert not manquantes, f"colonnes de l'ORM absentes après migration : {sorted(manquantes)}"

    def test_les_donnees_existantes_sont_preservees(self, base_avant):
        base_avant.executescript(self.FICHIER.read_text(encoding="utf-8"))

        ligne = base_avant.execute("SELECT form_points_5, ht_draw_rate FROM features").fetchone()

        assert ligne == (9.0, None)

    def test_une_seconde_execution_echoue_sans_rien_casser(self, base_avant):
        """SQLite refuse ADD COLUMN sur une colonne existante — c'est voulu.

        Le fichier le documente : une migration rejouée doit échouer bruyamment
        plutôt que de laisser croire qu'elle a fait quelque chose.
        """
        base_avant.executescript(self.FICHIER.read_text(encoding="utf-8"))

        with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
            base_avant.executescript(self.FICHIER.read_text(encoding="utf-8"))

        assert base_avant.execute("SELECT form_points_5 FROM features").fetchone() == (9.0,)


class TestToutesLesMigrations:
    def test_chaque_migration_exige_une_sauvegarde(self):
        """La règle de sécurité du projet doit être rappelée dans le fichier.

        « Ne jamais modifier la base sans sauvegarde préalable vérifiée » ne vaut
        que si elle est sous les yeux de qui lance la commande.
        """
        for fichier in sorted(MIGRATIONS.glob("*.sql")):
            contenu = fichier.read_text(encoding="utf-8").lower()
            assert "sauvegarde" in contenu, f"{fichier.name} ne rappelle pas la sauvegarde"

    def test_chaque_migration_est_transactionnelle(self):
        """Une migration interrompue ne doit pas laisser la base à moitié modifiée."""
        for fichier in sorted(MIGRATIONS.glob("*.sql")):
            contenu = fichier.read_text(encoding="utf-8").upper()
            if "ALTER TABLE" not in contenu and "UPDATE" not in contenu:
                continue
            assert "BEGIN" in contenu and "COMMIT" in contenu, (
                f"{fichier.name} modifie la base hors transaction"
            )
