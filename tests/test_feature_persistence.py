"""Tests de la persistance (upsert) des features."""

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal, engine
from app.models import Feature, Match, Team
from pipelines.feature_pipeline import persist_match_features


def _match_series(match_id: int, home_team_id: int, away_team_id: int) -> pd.Series:
    return pd.Series({
        "id": match_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
    })


def _cols(rest_days=None, elo_rating=None, goal_difference=None) -> dict:
    cols: dict = {}
    if rest_days is not None:
        cols["rest_days"] = rest_days
    if elo_rating is not None:
        cols["elo_rating"] = elo_rating
    if goal_difference is not None:
        cols["goal_difference"] = goal_difference
    return cols


@pytest.fixture
def match_and_teams():
    """Crée deux équipes et un match, retourne leurs identifiants."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        home = Team(canonical_name="Home FC", provider="test")
        away = Team(canonical_name="Away FC", provider="test")
        session.add_all([home, away])
        session.flush()
        match = Match(provider="test", home_team_id=home.id, away_team_id=away.id)
        session.add(match)
        session.flush()
        session.commit()
        return {
            "match_id": match.id,
            "home_team_id": home.id,
            "away_team_id": away.id,
        }
    finally:
        session.close()


class TestPersistMatchFeatures:
    def test_insert_creates_exactly_two_rows(self, match_and_teams):
        m = match_and_teams
        match = _match_series(m["match_id"], m["home_team_id"], m["away_team_id"])
        session = SessionLocal()
        try:
            persist_match_features(session, match, _cols(rest_days=15), _cols(rest_days=10))
            session.commit()
            rows = session.query(Feature).filter_by(match_id=m["match_id"]).all()
            assert len(rows) == 2
            assert {r.team_id for r in rows} == {m["home_team_id"], m["away_team_id"]}
        finally:
            session.close()

    def test_second_persist_no_duplicate(self, match_and_teams):
        m = match_and_teams
        match = _match_series(m["match_id"], m["home_team_id"], m["away_team_id"])
        session = SessionLocal()
        try:
            persist_match_features(session, match, _cols(rest_days=15), _cols(rest_days=10))
            session.commit()
            persist_match_features(session, match, _cols(rest_days=15), _cols(rest_days=10))
            session.commit()
            assert session.query(Feature).filter_by(match_id=m["match_id"]).count() == 2
        finally:
            session.close()

    def test_second_persist_updates_values(self, match_and_teams):
        m = match_and_teams
        match = _match_series(m["match_id"], m["home_team_id"], m["away_team_id"])
        session = SessionLocal()
        try:
            persist_match_features(session, match, _cols(rest_days=15), _cols(rest_days=10))
            session.commit()
            # Seconde persistance avec des valeurs différentes.
            persist_match_features(session, match, _cols(rest_days=7), _cols(rest_days=3))
            session.commit()
            home = session.query(Feature).filter_by(
                match_id=m["match_id"], team_id=m["home_team_id"]
            ).first()
            assert home.rest_days == 7
            assert session.query(Feature).filter_by(match_id=m["match_id"]).count() == 2
        finally:
            session.close()

    def test_rest_days_and_elo_side_by_side(self, match_and_teams):
        m = match_and_teams
        match = _match_series(m["match_id"], m["home_team_id"], m["away_team_id"])
        session = SessionLocal()
        try:
            persist_match_features(
                session,
                match,
                _cols(rest_days=15, elo_rating=1516.0),
                _cols(rest_days=10, elo_rating=1484.0),
            )
            session.commit()
            home = session.query(Feature).filter_by(
                match_id=m["match_id"], team_id=m["home_team_id"]
            ).first()
            away = session.query(Feature).filter_by(
                match_id=m["match_id"], team_id=m["away_team_id"]
            ).first()
            assert home.rest_days == 15
            assert home.elo_rating == pytest.approx(1516.0)
            assert away.rest_days == 10
            assert away.elo_rating == pytest.approx(1484.0)
        finally:
            session.close()

    def test_goal_difference_is_integer(self, match_and_teams):
        m = match_and_teams
        match = _match_series(m["match_id"], m["home_team_id"], m["away_team_id"])
        session = SessionLocal()
        try:
            persist_match_features(
                session, match, _cols(goal_difference=6), _cols(goal_difference=0)
            )
            session.commit()
            home = session.query(Feature).filter_by(
                match_id=m["match_id"], team_id=m["home_team_id"]
            ).first()
            assert home.goal_difference == 6
            assert isinstance(home.goal_difference, int)
        finally:
            session.close()

    def test_odds_movement_absent_or_none_no_error(self, match_and_teams):
        m = match_and_teams
        match = _match_series(m["match_id"], m["home_team_id"], m["away_team_id"])
        session = SessionLocal()
        try:
            # Sans clé odds_movement.
            persist_match_features(session, match, _cols(rest_days=15), _cols(rest_days=10))
            session.commit()
            # Avec clé odds_movement explicite à None.
            persist_match_features(
                session,
                match,
                {**_cols(rest_days=15), "odds_movement": None},
                {**_cols(rest_days=10), "odds_movement": None},
            )
            session.commit()
            assert session.query(Feature).filter_by(match_id=m["match_id"]).count() == 2
        finally:
            session.close()

    def test_invalid_match_team_raises_fk(self):
        session = SessionLocal()
        try:
            match = _match_series(99999, 99998, 99997)
            with pytest.raises(IntegrityError):
                persist_match_features(
                    session, match, _cols(rest_days=15), _cols(rest_days=10)
                )
                session.commit()
        finally:
            session.rollback()
            session.close()
