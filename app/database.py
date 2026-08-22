"""Configuration de la base de données SQLite."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


engine = create_engine(
    settings.database_url,
    echo=settings.app_debug,
    connect_args={"check_same_thread": False},
)

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
