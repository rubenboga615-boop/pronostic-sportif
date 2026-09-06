"""Simulation de ROI (Return on Investment)."""


def simulate_roi_by_strategy(
    predictions: list[dict],
    min_edge: float = 0.05,
    min_odds: float = 1.2,
    max_odds: float = 10.0,
    stake: float = 1.0,
) -> dict:
    """Simuler le ROI avec différentes stratégies de sélection."""
    # Stratégie 1 : Tous les paris
    all_bets = [(p["selection"], p["probability"], p["fair_odds"]) for p in predictions]

    # Stratégie 2 : Edge minimum
    edge_bets = [
        (p["selection"], p["probability"], p["fair_odds"])
        for p in predictions
        if p.get("edge", 0) >= min_edge
    ]

    # Stratégie 3 : Cotes dans la plage
    odds_bets = [
        (p["selection"], p["probability"], p["fair_odds"])
        for p in predictions
        if min_odds <= p["fair_odds"] <= max_odds
    ]

    return {
        "all_bets": len(all_bets),
        "edge_bets": len(edge_bets),
        "odds_bets": len(odds_bets),
        "strategies": {
            "all": {"count": len(all_bets)},
            "edge": {"count": len(edge_bets), "min_edge": min_edge},
            "odds_range": {"count": len(odds_bets), "range": f"{min_odds}-{max_odds}"},
        },
    }
