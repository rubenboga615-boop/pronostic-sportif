"""Configuration de la base de données SQLite."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


engine = create_engine(
    settings.database_url,
    echo=settings.app_debug,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Activer la vérification des clés étrangères pour chaque connexion SQLite.

    SQLite ne l'active pas par défaut ; ce listener garantit ``PRAGMA
    foreign_keys=ON`` sur chaque nouvelle connexion créée par le moteur.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Classe de base pour les modèles ORM."""
    pass


def get_db():
    """Dependency pour obtenir une session de base de données."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialiser les tables de la base de données."""
    Base.metadata.create_all(bind=engine)
