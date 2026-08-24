"""Tests du contexte de prédiction anti-fuite."""

from datetime import datetime

import pytest

from app.database import Base, SessionLocal, engine
from app.models import Competition, Feature, Match, Prediction, Team
from models.market_assembly import PUBLIC_MARKETS, PUBLIC_SELECTIONS
from models.prediction_context import build_match_predictions, build_prediction_context


@pytest.fixture
def env():
    """Compétition + 2 équipes, et helpers pour ajouter matchs et features."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    comp = Competition(name="L", country="C", provider_code="TEST")
    session.add(comp)
    session.flush()
    home = Team(canonical_name="H", provider="t")
    away = Team(canonical_name="A", provider="t")
    session.add_all([home, away])
    session.flush()
    session.commit()

    def add_match(home_id, away_id, date, hg=None, ag=None):
        m = Match(
            competition_id=comp.id,
            home_team_id=home_id,
            away_team_id=away_id,
            match_date=date,
            home_goals=hg,
            away_goals=ag,
            provider="t",
        )
        session.add(m)
        session.commit()
        return m.id

    def add_feature(match_id, team_id, goals_for=None, goals_against=None):
        f = Feature(
            match_id=match_id,
            team_id=team_id,
            goals_for_avg_5=goals_for,
            goals_against_avg_5=goals_against,
        )
        session.add(f)
        session.commit()
        return f

    try:
        yield {
            "session": session,
            "comp_id": comp.id,
            "home_id": home.id,
            "away_id": away.id,
            "add_match": add_match,
            "add_feature": add_feature,
        }
    finally:
        session.close()


def _setup_standard(env):
    """2 matchs historiques (2-0, 1-1) + un match cible (5-5) avec features."""
    env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 1), 2, 0)
    env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 15), 1, 1)
    tid = env["add_match"](env["home_id"], env["away_id"], datetime(2024, 3, 1), 5, 5)
    env["add_feature"](tid, env["home_id"], goals_for=1.5, goals_against=0.8)
    env["add_feature"](tid, env["away_id"], goals_for=1.0, goals_against=1.2)
    return tid


class TestPredictionContext:
    def test_valid_context(self, env):
        tid = _setup_standard(env)
        ctx = build_prediction_context(env["session"], tid)
        assert set(ctx) >= {
            "target_match",
            "home_features",
            "away_features",
            "league_avg_goals",
            "home_advantage",
            "lambda_home",
            "lambda_away",
        }
        assert ctx["lambda_home"] > 0
        assert ctx["lambda_away"] > 0

    def test_home_features_identified(self, env):
        tid = _setup_standard(env)
        ctx = build_prediction_context(env["session"], tid)
        assert ctx["home_features"]["goals_for_avg_5"] == pytest.approx(1.5)
        assert ctx["home_features"]["goals_against_avg_5"] == pytest.approx(0.8)

    def test_away_features_identified(self, env):
        tid = _setup_standard(env)
        ctx = build_prediction_context(env["session"], tid)
        assert ctx["away_features"]["goals_for_avg_5"] == pytest.approx(1.0)
        assert ctx["away_features"]["goals_against_avg_5"] == pytest.approx(1.2)

    def test_league_avg_goals(self, env):
        tid = _setup_standard(env)
        ctx = build_prediction_context(env["session"], tid)
        # (2+0)/2 = 1.0 ; (1+1)/2 = 1.0 ; moyenne = 1.0
        assert ctx["league_avg_goals"] == pytest.approx(1.0)

    def test_target_match_excluded(self, env):
        # Le match cible a un score (5-5) mais ne doit pas influencer la moyenne.
        tid = _setup_standard(env)
        ctx = build_prediction_context(env["session"], tid)
        assert ctx["league_avg_goals"] == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "label,date,hg,ag",
        [
            ("posterior", datetime(2024, 4, 1), 10, 0),
            ("same_date", datetime(2024, 3, 1), 9, 0),
        ],
    )
    def test_bad_matches_excluded(self, env, label, date, hg, ag):
        tid = _setup_standard(env)
        env["add_match"](env["home_id"], env["away_id"], date, hg, ag)
        ctx = build_prediction_context(env["session"], tid)
        assert ctx["league_avg_goals"] == pytest.approx(1.0)

    def test_null_scores_ignored(self, env):
        env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 1), 2, 0)
        env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 15), None, 1)
        tid = env["add_match"](env["home_id"], env["away_id"], datetime(2024, 3, 1), None, None)
        env["add_feature"](tid, env["home_id"])
        env["add_feature"](tid, env["away_id"])
        ctx = build_prediction_context(env["session"], tid)
        # Seul (2-0) compte : (2+0)/2 = 1.0
        assert ctx["league_avg_goals"] == pytest.approx(1.0)

    def test_no_history_raises(self, env):
        tid = env["add_match"](env["home_id"], env["away_id"], datetime(2024, 3, 1), None, None)
        env["add_feature"](tid, env["home_id"])
        env["add_feature"](tid, env["away_id"])
        with pytest.raises(ValueError):
            build_prediction_context(env["session"], tid)

    def test_missing_home_feature_raises(self, env):
        env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 1), 2, 0)
        tid = env["add_match"](env["home_id"], env["away_id"], datetime(2024, 3, 1), None, None)
        env["add_feature"](tid, env["away_id"])  # seulement extérieure
        with pytest.raises(LookupError):
            build_prediction_context(env["session"], tid)

    def test_missing_away_feature_raises(self, env):
        env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 1), 2, 0)
        tid = env["add_match"](env["home_id"], env["away_id"], datetime(2024, 3, 1), None, None)
        env["add_feature"](tid, env["home_id"])  # seulement domicile
        with pytest.raises(LookupError):
            build_prediction_context(env["session"], tid)

    def test_16_predictions(self, env):
        tid = _setup_standard(env)
        assert len(build_match_predictions(env["session"], tid)) == 16

    def test_public_contract(self, env):
        tid = _setup_standard(env)
        result = build_match_predictions(env["session"], tid)
        assert len(result) == 16
        for p in result:
            assert p["market"] in PUBLIC_MARKETS
            assert p["selection"] in PUBLIC_SELECTIONS[p["market"]]

    def test_no_db_write(self, env):
        tid = _setup_standard(env)
        before = env["session"].query(Prediction).count()
        build_match_predictions(env["session"], tid)
        after = env["session"].query(Prediction).count()
        assert before == after == 0
        assert env["session"].query(Feature).filter_by(match_id=tid).count() == 2

    def test_deterministic(self, env):
        tid = _setup_standard(env)
        r1 = build_match_predictions(env["session"], tid)
        r2 = build_match_predictions(env["session"], tid)
        assert r1 == r2

    def test_null_features_fallback(self, env):
        env["add_match"](env["home_id"], env["away_id"], datetime(2024, 2, 1), 2, 0)
        tid = env["add_match"](env["home_id"], env["away_id"], datetime(2024, 3, 1), None, None)
        env["add_feature"](tid, env["home_id"], goals_for=None, goals_against=None)
        env["add_feature"](tid, env["away_id"], goals_for=None, goals_against=None)

        result = build_match_predictions(env["session"], tid)
        assert len(result) == 16
        ctx = build_prediction_context(env["session"], tid)
        # Fallback neutre : lambda_home = avg * (1 + 0.25), lambda_away = avg.
        assert ctx["lambda_home"] == pytest.approx(ctx["league_avg_goals"] * 1.25)
        assert ctx["lambda_away"] == pytest.approx(ctx["league_avg_goals"])
