"""Tests d'intégration de run_feature_pipeline."""

from datetime import datetime

import pytest

from app.database import Base, SessionLocal, engine
from app.models import Competition, Feature, Match, OddsSnapshot, Team
from pipelines.feature_pipeline import run_feature_pipeline


@pytest.fixture
def populated_db():
    """Crée une compétition, 3 équipes, 5 matchs historiques, 1 match cible et des cotes.

    Renvoie les identifiants nécessaires aux assertions.
    """
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        comp = Competition(name="Test League", country="Test", provider_code="TEST")
        session.add(comp)
        session.flush()

        t1 = Team(canonical_name="T1", provider="test")
        t2 = Team(canonical_name="T2", provider="test")
        t3 = Team(canonical_name="T3", provider="test")
        session.add_all([t1, t2, t3])
        session.flush()

        def add_match(home, away, date, hg, ag):
            m = Match(
                provider="test",
                competition_id=comp.id,
                match_date=date,
                home_team_id=home.id,
                away_team_id=away.id,
                home_goals=hg,
                away_goals=ag,
                home_shots=10,
                away_shots=5,
                home_shots_on_target=5,
                away_shots_on_target=2,
            )
            session.add(m)
            return m

        # Historique strictement antérieur au match cible (2024-03-01).
        add_match(t1, t3, datetime(2024, 1, 10), 2, 0)
        add_match(t2, t3, datetime(2024, 1, 12), 1, 1)
        add_match(t3, t1, datetime(2024, 2, 10), 0, 3)
        add_match(t2, t1, datetime(2024, 2, 15), 1, 2)
        add_match(t3, t2, datetime(2024, 2, 20), 0, 1)

        # Match cible : T1 (domicile) vs T2 (extérieur), sans résultat.
        target = add_match(t1, t2, datetime(2024, 3, 1), None, None)
        session.flush()

        # Paires ouverture/clôture (B365 -> B365_close) pour home (2.0->1.8) et away (5.0->4.0).
        session.add_all([
            OddsSnapshot(
                match_id=target.id, bookmaker="B365", market="1N2",
                selection="home", odds=2.0, is_closing=False,
                captured_at=datetime(2024, 2, 1),
            ),
            OddsSnapshot(
                match_id=target.id, bookmaker="B365_close", market="1N2",
                selection="home", odds=1.8, is_closing=True,
                captured_at=datetime(2024, 2, 28),
            ),
            OddsSnapshot(
                match_id=target.id, bookmaker="B365", market="1N2",
                selection="away", odds=5.0, is_closing=False,
                captured_at=datetime(2024, 2, 1),
            ),
            OddsSnapshot(
                match_id=target.id, bookmaker="B365_close", market="1N2",
                selection="away", odds=4.0, is_closing=True,
                captured_at=datetime(2024, 2, 28),
            ),
        ])
        session.commit()

        return {
            "target_id": target.id,
            "t1": t1.id,
            "t2": t2.id,
        }
    finally:
        session.close()


class TestRunFeaturePipeline:
    def test_run_success(self, populated_db):
        result = run_feature_pipeline()
        assert result["matches_processed"] == 6

    def test_target_has_exactly_two_rows(self, populated_db):
        run_feature_pipeline()
        session = SessionLocal()
        try:
            rows = (
                session.query(Feature)
                .filter_by(match_id=populated_db["target_id"])
                .all()
            )
            assert len(rows) == 2
        finally:
            session.close()

    def test_target_feature_values(self, populated_db):
        run_feature_pipeline()
        session = SessionLocal()
        try:
            home = (
                session.query(Feature)
                .filter_by(match_id=populated_db["target_id"], team_id=populated_db["t1"])
                .first()
            )
            away = (
                session.query(Feature)
                .filter_by(match_id=populated_db["target_id"], team_id=populated_db["t2"])
                .first()
            )
            assert home is not None and away is not None
            # rest_days : T1 dernier match 2024-02-15 -> 15 jours ; T2 -> 10 jours.
            assert home.rest_days == 15
            assert away.rest_days == 10
            # goal_difference : T1 gf=7 ga=1 -> +6 ; T2 gf=3 ga=3 -> 0.
            assert home.goal_difference == 6
            assert away.goal_difference == 0
            # elo_rating : T1 plus fort (3 victoires) -> supérieur à T2.
            assert home.elo_rating > away.elo_rating
        finally:
            session.close()

    def test_target_odds_movement(self, populated_db):
        run_feature_pipeline()
        session = SessionLocal()
        try:
            home = (
                session.query(Feature)
                .filter_by(match_id=populated_db["target_id"], team_id=populated_db["t1"])
                .first()
            )
            away = (
                session.query(Feature)
                .filter_by(match_id=populated_db["target_id"], team_id=populated_db["t2"])
                .first()
            )
            # home -> "home" (2.0 -> 1.8) ; away -> "away" (5.0 -> 4.0).
            assert home.odds_movement == pytest.approx((1.8 - 2.0) / 2.0)
            assert away.odds_movement == pytest.approx((4.0 - 5.0) / 5.0)
        finally:
            session.close()

    def test_second_run_no_duplicates(self, populated_db):
        run_feature_pipeline()
        run_feature_pipeline()
        session = SessionLocal()
        try:
            count = (
                session.query(Feature)
                .filter_by(match_id=populated_db["target_id"])
                .count()
            )
            assert count == 2
        finally:
            session.close()

    def test_failure_rolls_back_completely(self, populated_db, monkeypatch):
        import pipelines.feature_pipeline as fp

        original = fp.persist_match_features
        calls = {"n": 0}

        def failing_persist(session, match, cols_home, cols_away):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("simulated failure")
            return original(session, match, cols_home, cols_away)

        monkeypatch.setattr(fp, "persist_match_features", failing_persist)

        with pytest.raises(RuntimeError):
            run_feature_pipeline()

        session = SessionLocal()
        try:
            assert session.query(Feature).count() == 0
        finally:
            session.close()

    def test_session_closed_after_success_and_exception(self, populated_db, monkeypatch):
        import pipelines.feature_pipeline as fp

        real_session_local = fp.SessionLocal
        instances = []

        class TrackingSession:
            def __init__(self):
                self._inner = real_session_local()
                self.closed = False

            def close(self):
                self.closed = True
                self._inner.close()

            def __getattr__(self, name):
                return getattr(self._inner, name)

        monkeypatch.setattr(
            fp, "SessionLocal",
            lambda: (instances.append(TrackingSession()) or instances[-1]),
        )

        # Succès : la session est fermée.
        run_feature_pipeline()
        assert instances[-1].closed is True

        # Exception : la session est toujours fermée.
        def always_fail(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(fp, "persist_match_features", always_fail)
        with pytest.raises(RuntimeError):
            run_feature_pipeline()
        assert instances[-1].closed is True
