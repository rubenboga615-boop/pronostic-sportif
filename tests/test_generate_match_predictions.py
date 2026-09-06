"""Tests end-to-end de generate_match_predictions (base temporaire via tmp_path)."""

import hashlib
import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import Base, Competition, Feature, Match, Prediction, Team
from models.market_assembly import PUBLIC_MARKETS, PUBLIC_SELECTIONS
from models.prediction_context import build_prediction_context
from pipelines.prediction_pipeline import generate_match_predictions

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
    """Crée une base SQLite temporaire avec schéma complet, retourne la session."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    yield session
    session.close()


def _seed_standard(session):
    """Historique (5 matchs 2-1) + match cible 2025-06-01 avec features.

    Retourne ``(target_id, home_id, away_id, comp_id)``.
    """
    comp = Competition(name="L", country="C", provider_code="TEST")
    session.add(comp)
    session.flush()

    home = Team(canonical_name="Home", provider="t")
    away = Team(canonical_name="Away", provider="t")
    session.add_all([home, away])
    session.flush()

    # Historique strictement antérieur : 5 × (2-1) → moyenne de ligue = 1.5
    for i in range(5):
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

    target = Match(
        competition_id=comp.id,
        home_team_id=home.id,
        away_team_id=away.id,
        match_date=datetime(2025, 6, 1),
        home_goals=0,
        away_goals=0,
        provider="t",
    )
    session.add(target)
    session.flush()

    session.add_all(
        [
            Feature(
                match_id=target.id,
                team_id=home.id,
                goals_for_avg_5=1.5,
                goals_against_avg_5=0.8,
            ),
            Feature(
                match_id=target.id,
                team_id=away.id,
                goals_for_avg_5=1.0,
                goals_against_avg_5=1.2,
            ),
        ]
    )
    session.commit()
    return target.id, home.id, away.id, comp.id


def _no_duplicates(session):
    dupes = session.execute(
        text(
            "SELECT match_id, model_version, market, selection, COUNT(*) as cnt "
            "FROM predictions GROUP BY match_id, model_version, market, selection "
            "HAVING cnt > 1"
        )
    ).fetchall()
    return dupes == []


class TestGenerateMatchPredictions:
    def test_generates_and_persists_16_predictions(self, db):
        target_id, *_ = _seed_standard(db)

        result = generate_match_predictions(db, target_id)

        assert len(result) == 16
        assert db.query(Prediction).count() == 16
        for p in db.query(Prediction).all():
            assert p.market in PUBLIC_MARKETS
            assert p.selection in PUBLIC_SELECTIONS[p.market]
            assert 0.0 <= p.probability <= 1.0
            assert p.fair_odds > 0
            assert p.model_version == "poisson-v1"
            assert p.generated_at is not None

    def test_second_run_no_duplicates(self, db):
        target_id, *_ = _seed_standard(db)

        result1 = generate_match_predictions(db, target_id)
        result2 = generate_match_predictions(db, target_id)

        assert len(result1) == 16
        assert len(result2) == 16
        assert db.query(Prediction).count() == 16
        assert _no_duplicates(db)

    def test_probabilities_updated_without_duplication(self, db):
        target_id, home_id, _, _ = _seed_standard(db)
        generate_match_predictions(db, target_id)

        first = (
            db.query(Prediction)
            .filter_by(match_id=target_id, market="1N2", selection="home")
            .first()
        )
        assert first is not None
        first_probability = first.probability  # copie avant la mise à jour

        # Nouvelle donnée : la feature domicile du match cible change.
        feature = (
            db.query(Feature)
            .filter_by(match_id=target_id, team_id=home_id)
            .first()
        )
        feature.goals_for_avg_5 = 3.0
        db.commit()

        generate_match_predictions(db, target_id)

        assert db.query(Prediction).count() == 16
        assert _no_duplicates(db)
        second = (
            db.query(Prediction)
            .filter_by(match_id=target_id, market="1N2", selection="home")
            .first()
        )
        assert second.probability != first_probability

    def test_anti_leakage_excludes_posterior_and_same_date(self, db):
        target_id, home_id, away_id, comp_id = _seed_standard(db)

        # Match postérieur (10-0) et match de même date (9-0) : ne doivent
        # jamais influencer la moyenne de ligue ni les prédictions.
        for date, hg, ag in [
            (datetime(2025, 6, 2), 10, 0),
            (datetime(2025, 6, 1), 9, 0),
        ]:
            bad = Match(
                competition_id=comp_id,
                home_team_id=home_id,
                away_team_id=away_id,
                match_date=date,
                home_goals=hg,
                away_goals=ag,
                provider="t",
            )
            db.add(bad)
        db.commit()

        generate_match_predictions(db, target_id)
        with_bad = {
            (p.market, p.selection): p.probability
            for p in db.query(Prediction).all()
        }

        # Retirer les matchs parasites (conserver le match cible) et repartir
        # d'une base de prédictions vide.
        db.query(Prediction).delete()
        db.query(Match).filter(
            Match.id != target_id, Match.match_date >= datetime(2025, 6, 1)
        ).delete()
        db.commit()

        generate_match_predictions(db, target_id)
        clean = {
            (p.market, p.selection): p.probability
            for p in db.query(Prediction).all()
        }

        assert with_bad == clean

        # La moyenne de ligue ne repose que sur l'historique antérieur : 1.5.
        ctx = build_prediction_context(db, target_id)
        assert ctx["league_avg_goals"] == pytest.approx(1.5)

    def test_existing_features_unchanged(self, db):
        target_id, *_ = _seed_standard(db)

        def snapshot():
            features = [
                (f.match_id, f.team_id, f.goals_for_avg_5, f.goals_against_avg_5)
                for f in db.query(Feature).order_by(Feature.id).all()
            ]
            return (
                db.query(Match).count(),
                len(features),
                features,
                db.execute(text("SELECT COUNT(*) FROM odds_snapshots")).scalar(),
            )

        before = snapshot()
        generate_match_predictions(db, target_id)
        after = snapshot()

        assert before == after

    def test_missing_match_raises_explicit_error(self, db):
        with pytest.raises(LookupError, match="introuvable"):
            generate_match_predictions(db, 99999)
        assert db.query(Prediction).count() == 0

    def test_no_history_raises_explicit_error(self, db):
        comp2 = Competition(name="L2", country="C2", provider_code="TEST2")
        db.add(comp2)
        db.flush()
        home = Team(canonical_name="H2", provider="t")
        away = Team(canonical_name="A2", provider="t")
        db.add_all([home, away])
        db.flush()

        # Match cible dans une compétition sans aucun historique antérieur.
        target = Match(
            competition_id=comp2.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=datetime(2025, 6, 1),
            provider="t",
        )
        db.add(target)
        db.flush()
        db.add_all(
            [
                Feature(match_id=target.id, team_id=home.id, goals_for_avg_5=1.5, goals_against_avg_5=0.8),
                Feature(match_id=target.id, team_id=away.id, goals_for_avg_5=1.0, goals_against_avg_5=1.2),
            ]
        )
        db.commit()

        with pytest.raises(ValueError, match="Aucun historique"):
            generate_match_predictions(db, target.id)
        assert db.query(Prediction).count() == 0

    def test_complete_rollback_on_failure(self, db, monkeypatch):
        import pipelines.prediction_pipeline as pp

        target_id, *_ = _seed_standard(db)

        original_init = pp.Prediction.__init__
        calls = {"n": 0}

        def patched_init(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("simulated failure")
            return original_init(self, *args, **kwargs)

        monkeypatch.setattr(pp.Prediction, "__init__", patched_init)

        with pytest.raises(RuntimeError, match="simulated failure"):
            pp.generate_match_predictions(db, target_id)

        # Aucune ligne partielle après rollback.
        assert db.query(Prediction).count() == 0


@requires_production_db
class TestOriginalDatabaseUntouched:
    def test_sha_size_mtime_unchanged(self, tmp_path):
        sha_before = hashlib.sha256(open(ORIG_DB, "rb").read()).hexdigest()
        size_before = os.path.getsize(ORIG_DB)
        mtime_before = os.path.getmtime(ORIG_DB)

        # Exécuter sur une base temporaire uniquement.
        engine = create_engine(f"sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        session = Session(engine)
        target_id, *_ = _seed_standard(session)
        generate_match_predictions(session, target_id)
        session.close()

        sha_after = hashlib.sha256(open(ORIG_DB, "rb").read()).hexdigest()
        size_after = os.path.getsize(ORIG_DB)
        mtime_after = os.path.getmtime(ORIG_DB)

        assert sha_before == sha_after
        assert size_before == size_after
        assert mtime_before == mtime_after