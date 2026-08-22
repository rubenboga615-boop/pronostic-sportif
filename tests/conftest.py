"""Conftest pour les tests - isole la base de données entre les tests."""

import pytest
from sqlalchemy import text

from app.database import Base, engine


@pytest.fixture(autouse=True)
def clean_database():
    """Nettoyer les tables de la base de données avant chaque test."""
    Base.metadata.create_all(bind=engine)
    yield
    # Nettoyer toutes les tables après chaque test
    with engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
        conn.commit()
