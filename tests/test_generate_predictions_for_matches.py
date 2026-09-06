"""Tests de generate_predictions_for_matches (base temporaire via tmp_path)."""

import hashlib
import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import Base, Competition, Feature, Match, Prediction, Team
from models.market_assembly import PUBLIC_MARKETS, PUBLIC_SELECTIONS
from pipelines.prediction_pipeline import generate_predictions_for_matches

ORIG_DB = "data/pronostic.db"

# La base de production n'est pas versionnée : sur un clone neuf ou en
# intégration continue, elle est absente et ce garde-fou n'a rien à vérifier.
# Il reste actif dès qu'elle existe, c'est-à-dire sur les machines où une
# écriture accidentelle serait réellement dommageable.
requires_production_db = pytest.mark.skipif(
    not os.path.exists(ORIG_DB),
    reason=f"{ORIG_DB} absent : garde-fou sans objet sur cette machine",
)


@pytest.fixture()
def db(tmp_path):
    """Crée une base temporaire avec schéma complet, retourne (engine, session)."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    yield session
    session.close()


def _seed_matches(session, n=2):
    """Préparer n matchs avec historique + features. Retourne les match_ids."""
    comp = Competition(name="L", country="C", provider_code="TEST")
    session.add(comp)
    session.flush()

    home = Team(canonical_name="Home", provider="t")
    away = Team(canonical_name="Away", provider="t")
    session.add_all([home, away])
    session.flush()

    # Historique pour la moyenne de la ligue
    for i in range(n + 5):
        m = Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=datetime(2024, 1, 1 + i),
            home_goals=2,
            away_goals=1,
            provider="t",
        )
        session.add(m)
    session.flush()

    # Matchs cibles + features
    match_ids = []
    for i in range(n):
        m = Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=datetime(2025, 6, 1 + i),
            home_goals=0,
            away_goals=0,
            provider="t",
        )
        session.add(m)
        session.flush()
        match_ids.append(m.id)

        fh = Feature(match_id=m.id, team_id=home.id, goals_for_avg_5=1.5, goals_against_avg_5=0.8)
        fa = Feature(match_id=m.id, team_id=away.id, goals_for_avg_5=1.0, goals_against_avg_5=1.2)
        session.add_all([fh, fa])

    session.commit()
    return match_ids


class TestGeneratePredictionsForMatches:
    def test_two_valid_matches_32_predictions(self, db):
        match_ids = _seed_matches(db, n=2)
        report = generate_predictions_for_matches(db, match_ids)

        assert report["succeeded"] == match_ids
        assert report["failed"] == []
        assert report["predictions_created_or_updated"] == 32
        assert db.query(Prediction).count() == 32

    def test_idempotent_second_call_no_duplicate(self, db):
        match_ids = _seed_matches(db, n=2)
        generate_predictions_for_matches(db, match_ids)
        report2 = generate_predictions_for_matches(db, match_ids)

        assert report2["succeeded"] == match_ids
        assert report2["failed"] == []
        assert report2["predictions_created_or_updated"] == 32
        assert db.query(Prediction).count() == 32

        # Vérifier l'absence de doublons
        dupes = db.execute(
            text(
                "SELECT match_id, model_version, market, selection, COUNT(*) as cnt "
                "FROM predictions GROUP BY match_id, model_version, market, selection "
                "HAVING cnt > 1"
            )
        ).fetchall()
        assert dupes == []

    def test_one_valid_one_invalid_partial_success(self, db):
        match_ids = _seed_matches(db, n=1)
        invalid_id = 99999
        report = generate_predictions_for_matches(db, [match_ids[0], invalid_id])

        assert report["succeeded"] == [match_ids[0]]
        assert len(report["failed"]) == 1
        assert report["failed"][0]["match_id"] == invalid_id
        assert "introuvable" in report["failed"][0]["error"]
        assert report["predictions_created_or_updated"] == 16
        assert db.query(Prediction).count() == 16

    def test_invalid_match_rollback_no_partial_write(self, db):
        """Un match invalide ne laisse aucune ligne partielle."""
        match_ids = _seed_matches(db, n=1)
        invalid_id = 99999
        generate_predictions_for_matches(db, [invalid_id])

        assert db.query(Prediction).count() == 0

    def test_tables_match_feature_odds_unchanged(self, db):
        match_ids = _seed_matches(db, n=2)
        n_matches = db.query(Match).count()
        n_features = db.query(Feature).count()
        n_odds = db.execute(text("SELECT COUNT(*) FROM odds_snapshots")).scalar()

        generate_predictions_for_matches(db, match_ids)

        assert db.query(Match).count() == n_matches
        assert db.query(Feature).count() == n_features
        assert db.execute(text("SELECT COUNT(*) FROM odds_snapshots")).scalar() == n_odds

    def test_valid_predictions_structure(self, db):
        match_ids = _seed_matches(db, n=1)
        report = generate_predictions_for_matches(db, match_ids)
        assert report["predictions_created_or_updated"] == 16

        preds = db.query(Prediction).all()
        assert len(preds) == 16
        for p in preds:
            assert p.market in PUBLIC_MARKETS
            assert p.selection in PUBLIC_SELECTIONS[p.market]
            assert 0.0 <= p.probability <= 1.0
            assert p.fair_odds > 0
            assert p.model_version == "poisson-v1"
            assert p.generated_at is not None

    def test_error_not_masked(self, db):
        """Les exceptions des matchs échoués sont préservées dans le rapport."""
        match_ids = _seed_matches(db, n=1)
        report = generate_predictions_for_matches(db, [match_ids[0], 42])
        assert len(report["failed"]) == 1
        assert report["failed"][0]["match_id"] == 42
        assert isinstance(report["failed"][0]["error"], str)
        assert len(report["failed"][0]["error"]) > 0


@requires_production_db
class TestOriginalDatabaseUntouched:
    def test_sha_size_mtime_unchanged(self):
        sha_before = hashlib.sha256(open(ORIG_DB, "rb").read()).hexdigest()
        size_before = os.path.getsize(ORIG_DB)
        mtime_before = os.path.getmtime(ORIG_DB)

        # Exécuter sur une DB temporaire (tmp_path via fixture ci-dessus)
        engine = create_engine(f"sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        session = Session(engine)
        _seed_matches(session, n=1)
        generate_predictions_for_matches(session, [session.query(Match).first().id])
        session.close()

        sha_after = hashlib.sha256(open(ORIG_DB, "rb").read()).hexdigest()
        size_after = os.path.getsize(ORIG_DB)
        mtime_after = os.path.getmtime(ORIG_DB)

        assert sha_before == sha_after
        assert size_before == size_after
        assert mtime_before == mtime_after
