"""Tests du pipeline de prédiction intégré (base temporaire)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import Base, Competition, Feature, Match, Prediction, Team
from pipelines.prediction_pipeline import (
    _select_matches_ready_for_prediction,
    run_prediction_pipeline,
)

ORIG_DB = "data/pronostic.db"

# Date de coupure fixe pour tous les tests : jamais dérivée de datetime.now().
# L'historique des seeds se situe en 2024, les matchs cibles en 2025-06.
REFERENCE_DATE = datetime(2025, 1, 1)


def _make_db(tmp_path):
    """Créer une base temporaire avec schéma complet."""
    db_path = tmp_path / "test_pipeline.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    return engine


def _seed(engine, n_matches=3):
    """Préparer n matchs avec historique + features. Retourne (session, match_ids)."""
    session = Session(engine)
    comp = Competition(name="L", country="C", provider_code="TEST")
    session.add(comp)
    session.flush()

    home = Team(canonical_name="Home", provider="t")
    away = Team(canonical_name="Away", provider="t")
    session.add_all([home, away])
    session.flush()

    # Historique pour la moyenne de la ligue (strictement antérieur à REFERENCE_DATE)
    for i in range(n_matches + 5):
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

    # Matchs cibles + features (strictement postérieurs à REFERENCE_DATE)
    match_ids = []
    for i in range(n_matches):
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
    return session, match_ids


def _seed_candidates(engine):
    """Jeu de candidats couvrant tous les cas de la règle temporelle.

    Historique antérieur (2024) + six candidats : passé, même date que la
    référence, futur complet, sans date, futur sans feature domicile, futur
    sans feature extérieure. Retourne les ids et la date de référence.
    """
    session = Session(engine)
    comp = Competition(name="L", country="C", provider_code="TEST")
    session.add(comp)
    session.flush()

    home = Team(canonical_name="Home", provider="t")
    away = Team(canonical_name="Away", provider="t")
    session.add_all([home, away])
    session.flush()

    def add_match(date, hg=None, ag=None):
        m = Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=date,
            home_goals=hg,
            away_goals=ag,
            provider="t",
        )
        session.add(m)
        session.flush()
        return m.id

    def add_features(match_id, *, with_home=True, with_away=True):
        if with_home:
            session.add(Feature(
                match_id=match_id, team_id=home.id,
                goals_for_avg_5=1.5, goals_against_avg_5=0.8,
            ))
        if with_away:
            session.add(Feature(
                match_id=match_id, team_id=away.id,
                goals_for_avg_5=1.0, goals_against_avg_5=1.2,
            ))

    # Historique strictement antérieur (moyenne de ligue), jamais sélectionné.
    for i in range(3):
        add_match(datetime(2024, 1, 1 + i), 2, 1)

    ref = datetime(2025, 1, 1)

    past_id = add_match(datetime(2024, 12, 1), 1, 1)  # passé → exclu
    add_features(past_id)

    same_id = add_match(ref, 0, 0)  # même date que la référence → exclu
    add_features(same_id)

    future_id = add_match(datetime(2025, 6, 1))  # futur → inclus
    add_features(future_id)

    no_date_id = add_match(None)  # sans date → exclu
    add_features(no_date_id)

    no_home_id = add_match(datetime(2025, 6, 2))  # futur sans feature domicile → exclu
    add_features(no_home_id, with_home=False)

    no_away_id = add_match(datetime(2025, 6, 3))  # futur sans feature extérieure → exclu
    add_features(no_away_id, with_away=False)

    session.commit()
    session.close()
    return {
        "ref": ref,
        "past": past_id,
        "same": same_id,
        "future": future_id,
        "no_date": no_date_id,
        "no_home": no_home_id,
        "no_away": no_away_id,
    }


def _seed_760_historical(engine):
    """Reproduire la base réelle : 760 matchs terminés avec features.

    Dates étalées un match par jour depuis 2023-08-11, comme
    ``data/pronostic.db``. Tous les matchs sont complets ET ont deux lignes
    ``Feature`` : seule la règle temporelle peut les exclure.

    Retourne la date du dernier match du lot.
    """
    session = Session(engine)
    comp = Competition(name="H", country="C", provider_code="HIST")
    session.add(comp)
    session.flush()

    home = Team(canonical_name="H1", provider="t")
    away = Team(canonical_name="H2", provider="t")
    session.add_all([home, away])
    session.flush()

    start = datetime(2023, 8, 11)
    matches = []
    for i in range(760):
        matches.append(Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=start + timedelta(days=i),
            home_goals=1 + (i % 3),
            away_goals=i % 3,
            provider="t",
        ))
    session.add_all(matches)
    session.flush()

    features = []
    for m in matches:
        features.append(Feature(
            match_id=m.id, team_id=home.id,
            goals_for_avg_5=1.5, goals_against_avg_5=0.8,
        ))
        features.append(Feature(
            match_id=m.id, team_id=away.id,
            goals_for_avg_5=1.0, goals_against_avg_5=1.2,
        ))
    session.add_all(features)

    session.commit()
    session.close()
    return start + timedelta(days=759)


class TestSelectMatchesReady:
    def test_selects_matches_with_features(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)
        session.close()

        with Session(engine) as s:
            result = _select_matches_ready_for_prediction(s, REFERENCE_DATE)
        assert sorted(result) == sorted(match_ids)

    def test_excludes_match_without_features(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)

        # Ajouter un match futur sans features
        comp = session.query(Competition).first()
        home = session.query(Team).first()
        away = session.query(Team).all()[1]
        m = Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=datetime(2025, 7, 1),
            provider="t",
        )
        session.add(m)
        session.commit()
        bad_id = m.id
        session.close()

        with Session(engine) as s:
            result = _select_matches_ready_for_prediction(s, REFERENCE_DATE)
        assert bad_id not in result
        assert sorted(result) == sorted(match_ids)

    def test_excludes_match_without_date(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)

        comp = session.query(Competition).first()
        home = session.query(Team).first()
        away = session.query(Team).all()[1]
        m = Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=None,
            provider="t",
        )
        session.add(m)
        session.flush()
        fh = Feature(match_id=m.id, team_id=home.id, goals_for_avg_5=1.0, goals_against_avg_5=1.0)
        fa = Feature(match_id=m.id, team_id=away.id, goals_for_avg_5=1.0, goals_against_avg_5=1.0)
        session.add_all([fh, fa])
        session.commit()
        bad_id = m.id
        session.close()

        with Session(engine) as s:
            result = _select_matches_ready_for_prediction(s, REFERENCE_DATE)
        assert bad_id not in result

    def test_empty_database(self, tmp_path):
        engine = _make_db(tmp_path)
        with Session(engine) as s:
            result = _select_matches_ready_for_prediction(s, REFERENCE_DATE)
        assert result == []


class TestSelectMatchesReferenceDate:
    """Règle temporelle : seuls les matchs strictement postérieurs à la date
    de référence sont sélectionnés, sans jamais appeler datetime.now()."""

    def _select(self, engine, ref):
        with Session(engine) as s:
            return _select_matches_ready_for_prediction(s, ref)

    def test_past_match_excluded(self, tmp_path):
        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)
        result = self._select(engine, ids["ref"])
        assert ids["past"] not in result

    def test_match_at_reference_date_excluded(self, tmp_path):
        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)
        result = self._select(engine, ids["ref"])
        assert ids["same"] not in result

    def test_future_match_included(self, tmp_path):
        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)
        result = self._select(engine, ids["ref"])
        assert result == [ids["future"]]

    def test_match_without_date_excluded(self, tmp_path):
        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)
        result = self._select(engine, ids["ref"])
        assert ids["no_date"] not in result

    def test_future_without_home_feature_excluded(self, tmp_path):
        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)
        result = self._select(engine, ids["ref"])
        assert ids["no_home"] not in result

    def test_future_without_away_feature_excluded(self, tmp_path):
        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)
        result = self._select(engine, ids["ref"])
        assert ids["no_away"] not in result

    def test_760_historical_matches_not_selected(self, tmp_path):
        """Avec une référence après leur période, aucun des 760 matchs
        historiques n'est sélectionné, alors que tous ont des features."""
        engine = _make_db(tmp_path)
        last_date = _seed_760_historical(engine)
        ref_after_period = last_date + timedelta(days=1)
        result = self._select(engine, ref_after_period)
        assert result == []
        with Session(engine) as s:
            # Preuve : l'exclusion ne vient pas de l'absence de features.
            assert s.query(Match).count() == 760
            assert s.query(Feature).count() == 1520

    def test_deterministic_with_same_reference_date(self, tmp_path):
        engine = _make_db(tmp_path)
        _seed_candidates(engine)
        r1 = self._select(engine, REFERENCE_DATE)
        r2 = self._select(engine, REFERENCE_DATE)
        assert r1 == r2
        assert r1 != []

    def test_no_implicit_datetime_now(self, tmp_path, monkeypatch):
        """La sélection fonctionne même si datetime.now() est rendu inutilisable :
        la date de coupure est toujours fournie explicitement par l'appelant."""
        import pipelines.prediction_pipeline as pp

        engine = _make_db(tmp_path)
        ids = _seed_candidates(engine)

        class _NoNow:
            @staticmethod
            def now(*args, **kwargs):
                raise AssertionError(
                    "datetime.now() ne doit jamais être appelé implicitement"
                )

        monkeypatch.setattr(pp, "datetime", _NoNow)
        result = self._select(engine, ids["ref"])
        assert result == [ids["future"]]

    def test_reference_date_is_required(self, tmp_path):
        engine = _make_db(tmp_path)
        _seed_candidates(engine)
        with pytest.raises(ValueError, match="reference_date est obligatoire"):
            self._select(engine, None)


class TestRunPredictionPipeline:
    def test_full_pipeline_creates_predictions(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)
        session.close()

        report = run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        assert report["predictions_created_or_updated"] == len(match_ids) * 16
        assert len(report["succeeded"]) == len(match_ids)
        assert report["failed"] == []

        with Session(engine) as s:
            assert s.query(Prediction).count() == len(match_ids) * 16

    def test_pipeline_idempotent(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)
        session.close()

        run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)
        report2 = run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        assert report2["predictions_created_or_updated"] == len(match_ids) * 16
        assert report2["failed"] == []

        with Session(engine) as s:
            assert s.query(Prediction).count() == len(match_ids) * 16
            dupes = s.execute(text(
                "SELECT match_id, market, selection, COUNT(*) FROM predictions "
                "GROUP BY match_id, market, selection HAVING COUNT(*) > 1"
            )).fetchall()
            assert dupes == []

    def test_pipeline_partial_failure(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine, n_matches=2)

        # Ajouter un match avec features mais dans une 2e compétition
        # sans historique → _compute_league_avg_goals va échouer
        comp2 = Competition(name="L2", country="C2", provider_code="TEST2")
        session.add(comp2)
        session.flush()

        home = session.query(Team).first()
        away = session.query(Team).all()[1]
        bad_match = Match(
            competition_id=comp2.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=datetime(2025, 8, 1),
            provider="t",
        )
        session.add(bad_match)
        session.flush()
        fh = Feature(
            match_id=bad_match.id, team_id=home.id,
            goals_for_avg_5=1.0, goals_against_avg_5=1.0,
        )
        fa = Feature(
            match_id=bad_match.id, team_id=away.id,
            goals_for_avg_5=1.0, goals_against_avg_5=1.0,
        )
        session.add_all([fh, fa])
        session.commit()
        bad_id = bad_match.id
        session.close()

        report = run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        assert report["predictions_created_or_updated"] == len(match_ids) * 16
        assert len(report["succeeded"]) == len(match_ids)
        assert len(report["failed"]) == 1
        assert report["failed"][0]["match_id"] == bad_id

    def test_pipeline_no_matches(self, tmp_path):
        engine = _make_db(tmp_path)
        report = run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        assert report["predictions_created_or_updated"] == 0
        assert report["succeeded"] == []
        assert report["failed"] == []

    def test_pipeline_skips_historical_matches(self, tmp_path):
        """Un match terminé daté avant la coupure n'est pas prédit, même avec
        des features : aucune prédiction n'est créée pour lui."""
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)

        comp = session.query(Competition).first()
        home = session.query(Team).first()
        away = session.query(Team).all()[1]
        old = Match(
            competition_id=comp.id,
            home_team_id=home.id,
            away_team_id=away.id,
            match_date=datetime(2024, 6, 1),
            home_goals=3,
            away_goals=1,
            provider="t",
        )
        session.add(old)
        session.flush()
        session.add_all([
            Feature(
                match_id=old.id, team_id=home.id,
                goals_for_avg_5=1.5, goals_against_avg_5=0.8,
            ),
            Feature(
                match_id=old.id, team_id=away.id,
                goals_for_avg_5=1.0, goals_against_avg_5=1.2,
            ),
        ])
        session.commit()
        old_id = old.id
        session.close()

        report = run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        assert sorted(report["succeeded"]) == sorted(match_ids)
        assert old_id not in report["succeeded"]
        with Session(engine) as s:
            assert s.query(Prediction).count() == len(match_ids) * 16
            assert s.query(Prediction).filter_by(match_id=old_id).count() == 0

    def test_reference_date_mandatory(self, tmp_path):
        """Le contrat exige une date de coupure explicite de la part de
        l'appelant : omise (TypeError) ou None (ValueError) = refus."""
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)
        session.close()

        with pytest.raises(TypeError):
            run_prediction_pipeline(engine=engine)
        with pytest.raises(ValueError, match="reference_date est obligatoire"):
            run_prediction_pipeline(engine=engine, reference_date=None)

    def test_tables_unchanged(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)
        n_matches = session.query(Match).count()
        n_features = session.query(Feature).count()
        n_odds = session.execute(text("SELECT COUNT(*) FROM odds_snapshots")).scalar()
        session.close()

        run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        with Session(engine) as s:
            assert s.query(Match).count() == n_matches
            assert s.query(Feature).count() == n_features
            assert s.execute(text("SELECT COUNT(*) FROM odds_snapshots")).scalar() == n_odds

    def test_model_version_used(self, tmp_path):
        engine = _make_db(tmp_path)
        session, match_ids = _seed(engine)
        session.close()

        run_prediction_pipeline(
            engine=engine, model_version="test-v2", reference_date=REFERENCE_DATE
        )

        with Session(engine) as s:
            versions = s.execute(text(
                "SELECT DISTINCT model_version FROM predictions"
            )).fetchall()
            assert len(versions) == 1
            assert versions[0][0] == "test-v2"


class TestOriginalDatabaseUntouched:
    def test_sha_size_mtime_unchanged(self):
        import hashlib
        import os

        sha_before = hashlib.sha256(open(ORIG_DB, "rb").read()).hexdigest()
        size_before = os.path.getsize(ORIG_DB)
        mtime_before = os.path.getmtime(ORIG_DB)

        # Exécuter le pipeline sur une DB temporaire
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        session, _ = _seed(engine, n_matches=1)
        session.close()
        run_prediction_pipeline(engine=engine, reference_date=REFERENCE_DATE)

        sha_after = hashlib.sha256(open(ORIG_DB, "rb").read()).hexdigest()
        size_after = os.path.getsize(ORIG_DB)
        mtime_after = os.path.getmtime(ORIG_DB)

        assert sha_before == sha_after
        assert size_before == size_after
        assert mtime_before == mtime_after
