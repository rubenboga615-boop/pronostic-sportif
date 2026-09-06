"""Tests de la persistance idempotente des prédictions (base temporaire)."""

import pytest
from sqlalchemy import text

from app.database import Base, SessionLocal, engine
from app.models import Competition, Match, Prediction, Team
from models.market_assembly import build_match_markets
from pipelines.prediction_pipeline import persist_predictions

PREDICTIONS = build_match_markets({"goals_for_avg_5": 1.5}, {"goals_against_avg_5": 1.2}, 1.4)


@pytest.fixture
def env():
    """Compétition + équipes + match (pour la FK), retourne session et match_id."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    comp = Competition(name="L", country="C", provider_code="TEST")
    session.add(comp)
    session.flush()
    home = Team(canonical_name="H", provider="t")
    away = Team(canonical_name="A", provider="t")
    session.add_all([home, away])
    session.flush()
    m = Match(competition_id=comp.id, home_team_id=home.id, away_team_id=away.id, provider="t")
    session.add(m)
    session.flush()
    session.commit()
    try:
        yield {"session": session, "match_id": m.id}
    finally:
        session.close()


class TestPersistPredictions:
    def test_initial_insert_16(self, env):
        result = persist_predictions(env["session"], env["match_id"], "v1", PREDICTIONS)
        assert len(result) == 16
        assert env["session"].query(Prediction).count() == 16

    def test_second_identical_call_no_duplicate(self, env):
        persist_predictions(env["session"], env["match_id"], "v1", PREDICTIONS)
        persist_predictions(env["session"], env["match_id"], "v1", PREDICTIONS)
        assert env["session"].query(Prediction).count() == 16

    def test_second_call_modified_updates(self, env):
        persist_predictions(env["session"], env["match_id"], "v1", PREDICTIONS)
        modified = [dict(p) for p in PREDICTIONS]
        modified[0]["probability"] = 0.99
        persist_predictions(env["session"], env["match_id"], "v1", modified)
        assert env["session"].query(Prediction).count() == 16
        row = (
            env["session"]
            .query(Prediction)
            .filter_by(
                match_id=env["match_id"],
                model_version="v1",
                market=PREDICTIONS[0]["market"],
                selection=PREDICTIONS[0]["selection"],
            )
            .first()
        )
        assert row.probability == pytest.approx(0.99)

    def test_contradictory_duplicates_rejected(self, env):
        base = {"market": "1N2", "selection": "home", "probability": 0.5, "fair_odds": 2.0}
        contradictory = [dict(base), {**base, "probability": 0.6, "fair_odds": 1.6667}]
        with pytest.raises(ValueError):
            persist_predictions(env["session"], env["match_id"], "v1", contradictory)
        assert env["session"].query(Prediction).count() == 0

    def test_identical_duplicates_accepted(self, env):
        base = {"market": "1N2", "selection": "home", "probability": 0.5, "fair_odds": 2.0}
        result = persist_predictions(
            env["session"], env["match_id"], "v1", [dict(base), dict(base)]
        )
        assert len(result) == 1
        assert env["session"].query(Prediction).count() == 1

    def test_missing_match_raises(self, env):
        with pytest.raises(LookupError):
            persist_predictions(env["session"], 99999, "v1", PREDICTIONS)
        assert env["session"].query(Prediction).count() == 0

    def test_unknown_market_raises(self, env):
        bad = [{"market": "unknown", "selection": "home", "probability": 0.5, "fair_odds": 2.0}]
        with pytest.raises(ValueError):
            persist_predictions(env["session"], env["match_id"], "v1", bad)
        assert env["session"].query(Prediction).count() == 0

    def test_unknown_selection_raises(self, env):
        bad = [{"market": "1N2", "selection": "unknown", "probability": 0.5, "fair_odds": 2.0}]
        with pytest.raises(ValueError):
            persist_predictions(env["session"], env["match_id"], "v1", bad)
        assert env["session"].query(Prediction).count() == 0

    def test_probability_out_of_range_raises(self, env):
        bad = [{"market": "1N2", "selection": "home", "probability": 1.5, "fair_odds": 2.0}]
        with pytest.raises(ValueError):
            persist_predictions(env["session"], env["match_id"], "v1", bad)
        assert env["session"].query(Prediction).count() == 0

    def test_fair_odds_non_positive_raises(self, env):
        bad = [{"market": "1N2", "selection": "home", "probability": 0.5, "fair_odds": 0.0}]
        with pytest.raises(ValueError):
            persist_predictions(env["session"], env["match_id"], "v1", bad)
        assert env["session"].query(Prediction).count() == 0

    def test_unaffected_columns_unchanged(self, env):
        session = env["session"]
        persist_predictions(session, env["match_id"], "v1", PREDICTIONS)
        first = PREDICTIONS[0]
        row = (
            session.query(Prediction)
            .filter_by(
                match_id=env["match_id"],
                model_version="v1",
                market=first["market"],
                selection=first["selection"],
            )
            .first()
        )
        row.offered_odds = 2.5
        row.edge = 0.1
        row.confidence = 0.9
        row.data_quality = 0.8
        row.status = "validated"
        session.commit()

        modified = [dict(p) for p in PREDICTIONS]
        modified[0]["probability"] = 0.99
        persist_predictions(session, env["match_id"], "v1", modified)

        row2 = (
            session.query(Prediction)
            .filter_by(
                match_id=env["match_id"],
                model_version="v1",
                market=first["market"],
                selection=first["selection"],
            )
            .first()
        )
        assert row2.offered_odds == 2.5
        assert row2.edge == 0.1
        assert row2.confidence == 0.9
        assert row2.data_quality == 0.8
        assert row2.status == "validated"
        assert row2.probability == pytest.approx(0.99)

    def test_foreign_keys_enabled(self, env):
        fk = env["session"].execute(text("PRAGMA foreign_keys")).scalar()
        assert fk == 1

    def test_exception_midway_rolls_back(self, env, monkeypatch):
        import pipelines.prediction_pipeline as pp

        original_init = pp.Prediction.__init__
        calls = {"n": 0}

        def patched_init(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("simulated failure")
            return original_init(self, *args, **kwargs)

        monkeypatch.setattr(pp.Prediction, "__init__", patched_init)

        with pytest.raises(RuntimeError):
            pp.persist_predictions(env["session"], env["match_id"], "v1", PREDICTIONS)

        # Aucune ligne partiellement persistée après rollback.
        assert env["session"].query(Prediction).count() == 0
