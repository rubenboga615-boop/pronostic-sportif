"""Tests du calcul du mouvement de cote (odds_movement)."""

import pandas as pd
import pytest

from features.odds_movement import calculate_odds_movement


def _pair(match_id=1, market="1N2", selection="home", opening=2.0, closing=1.8):
    """Paire ouverture/clôture (B365 / B365_close) pour une sélection."""
    return pd.DataFrame({
        "match_id": [match_id, match_id],
        "market": [market, market],
        "selection": [selection, selection],
        "bookmaker": ["B365", "B365_close"],
        "is_closing": [0, 1],
        "odds": [opening, closing],
    })


class TestOddsMovement:
    def test_home_opening_closing(self):
        result = calculate_odds_movement(_pair(), match_id=1)
        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_draw_and_away_independent(self):
        for selection, opening, closing in [("draw", 3.5, 3.0), ("away", 5.0, 4.0)]:
            result = calculate_odds_movement(
                _pair(selection=selection, opening=opening, closing=closing),
                match_id=1,
                selection=selection,
            )
            assert result["odds_movement"] == pytest.approx((closing - opening) / opening)

    def test_other_selection_never_used(self):
        # La sélection "home" ne doit pas être affectée par la sélection "away".
        frame = pd.concat([
            _pair(selection="home", opening=2.0, closing=1.8),
            _pair(selection="away", opening=10.0, closing=5.0),
        ], ignore_index=True)
        result = calculate_odds_movement(frame, match_id=1, selection="home")
        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_other_bookmaker_never_forms_pair(self):
        # Un bookmaker d'ouverture (BW) ne forme pas de paire avec B365_close.
        frame = pd.DataFrame({
            "match_id": [1, 1],
            "market": ["1N2", "1N2"],
            "selection": ["home", "home"],
            "bookmaker": ["BW", "B365_close"],
            "is_closing": [0, 1],
            "odds": [2.2, 1.8],
        })
        result = calculate_odds_movement(frame, match_id=1, selection="home")
        assert result["odds_movement"] is None

    def test_opening_missing(self):
        frame = _pair()
        frame = frame[frame["bookmaker"] == "B365_close"]
        result = calculate_odds_movement(frame, match_id=1)
        assert result["odds_movement"] is None

    def test_closing_missing(self):
        frame = _pair()
        frame = frame[frame["bookmaker"] == "B365"]
        result = calculate_odds_movement(frame, match_id=1)
        assert result["odds_movement"] is None

    def test_opening_non_positive(self):
        result = calculate_odds_movement(_pair(opening=0.0), match_id=1)
        assert result["odds_movement"] is None

    def test_different_market(self):
        result = calculate_odds_movement(_pair(market="btts"), match_id=1)
        assert result["odds_movement"] is None

    def test_default_market_and_selection(self):
        # Défauts market="1N2" et selection="home" sans les passer explicitement.
        result = calculate_odds_movement(_pair(), match_id=1)
        assert result["odds_movement"] is not None
        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)
