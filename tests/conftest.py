"""Conftest pour les tests — isolation de la base de données.

La base de production (``data/pronostic.db``) ne doit JAMAIS être touchée par
les tests. Pour cela :

1. on force ``DATABASE_URL`` vers une base SQLite **temporaire dédiée** (hors du
   dépôt) **avant tout import de l'application**, car ``app.config`` et
   ``app.database`` lisent ``DATABASE_URL`` au moment de leur import ;
2. un garde-fou vérifie explicitement, au démarrage de la session de test, que
   la base pointée n'est pas la production.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# 1) Base de test temporaire, forcée AVANT tout import de l'app
# ─────────────────────────────────────────────────────────────
PRODUCTION_DB_PATH = Path("data/pronostic.db")

# Répertoire temporaire créé hors du dépôt, supprimé à la fin du processus.
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="pronostic-tests-"))
atexit.register(shutil.rmtree, _TEST_TMP_DIR, ignore_errors=True)
TEST_DB_PATH = _TEST_TMP_DIR / "test.db"

# Affectation directe (pas setdefault) : on écrase toute valeur issue du shell
# pour garantir qu'aucun test ne puisse pointer vers la production.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import pytest
from sqlalchemy import text

from app.config import settings
from app.database import Base, engine


# ─────────────────────────────────────────────────────────────
# 2) Garde-fou anti-production
# ─────────────────────────────────────────────────────────────

def _sqlite_path(url: str) -> Path:
    """Extraire le chemin de fichier depuis une URL SQLite.

    Gère ``sqlite:///rel/path`` (3 slashs) et ``sqlite:////abs/path`` (4 slashs).
    """
    return Path(url.replace("sqlite:///", "")).resolve()


def _is_production_database(url: str) -> bool:
    """Déterminer si une URL SQLite pointe vers la base de production."""
    return _sqlite_path(url) == PRODUCTION_DB_PATH.resolve()


def _ensure_test_database(url: str) -> None:
    """Refuser de lancer les tests si la base pointée est la production."""
    if _is_production_database(url):
        raise RuntimeError(
            f"Refus d'exécuter les tests : la base configurée est la production "
            f"({url}). Les tests doivent utiliser une base dédiée."
        )


@pytest.fixture(scope="session", autouse=True)
def guard_against_production_database():
    """Garde-fou : bloquer la session de test si on pointe vers la production."""
    _ensure_test_database(settings.database_url)


# ─────────────────────────────────────────────────────────────
# 3) Nettoyage de la base de test entre chaque test
# ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_database():
    """Créer les tables puis vider la base DE TEST après chaque test."""
    Base.metadata.create_all(bind=engine)
    yield
    # Nettoyer toutes les tables (base de test uniquement) après chaque test
    with engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
        conn.commit()


# ─────────────────────────────────────────────────────────────
# 4) Isolation des chemins de données
# ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_data_dirs(tmp_path, monkeypatch):
    """Rediriger les répertoires d'écriture vers un dossier temporaire.

    Évite que les tests n'écrivent dans les chemins de production
    (``data/raw``, ``data/cleaned``). Le monkeypatch est réversible et propre
    à chaque test.
    """
    monkeypatch.setattr(settings, "raw_dir", tmp_path / "raw")
    monkeypatch.setattr(settings, "cleaned_dir", tmp_path / "cleaned")
    yield
