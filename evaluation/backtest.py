"""Backtest chronologique du modèle de pronostic."""

import pandas as pd
from loguru import logger

from evaluation.metrics import accuracy, brier_score, log_loss, roi_simulation


def chronological_split(
    matches_df: pd.DataFrame,
    train_end: str = "2022-06-30",
    val_end: str = "2023-06-30",
    test_end: str = "2024-06-30",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Découpage chronologique des données.
    
    Returns:
        (train, validation, test, test_recent)
    """
    train = matches_df[matches_df["match_date"] <= train_end]
    validation = matches_df[
        (matches_df["match_date"] > train_end) & (matches_df["match_date"] <= val_end)
    ]
    test = matches_df[
        (matches_df["match_date"] > val_end) & (matches_df["match_date"] <= test_end)
    ]
    test_recent = matches_df[matches_df["match_date"] > test_end]

    logger.info(
        f"Split chronologique : train={len(train)}, "
        f"val={len(validation)}, test={len(test)}, "
        f"test_recent={len(test_recent)}"
    )

    return train, validation, test, test_recent


def run_backtest(
    predictions: pd.DataFrame,
    actual_results: pd.DataFrame,
    market: str,
) -> dict:
    """Exécuter un backtest pour un marché donné."""
    # Filtrer par marché
    pred_market = predictions[predictions["market"] == market].copy()
    actual_market = actual_results[actual_results["market"] == market].copy()

    # Fusionner
    merged = pred_market.merge(
        actual_market[["match_id", "actual_outcome"]],
        on="match_id",
        how="inner",
    )

    if merged.empty:
        return {"error": "Pas de données suffisantes"}

    y_true = merged["actual_outcome"].tolist()
    y_pred = merged["selection"].tolist()
    y_prob = merged["probability"].tolist()
    odds = merged["fair_odds"].tolist()

    results = {
        "market": market,
        "n_matches": len(merged),
        "accuracy": accuracy(y_true, y_pred),
        "brier_score": brier_score(
            [1 if t == p else 0 for t, p in zip(y_true, y_pred)],
            y_prob,
        ),
        "log_loss": log_loss(
            [1 if t == p else 0 for t, p in zip(y_true, y_pred)],
            y_prob,
        ),
        "roi": roi_simulation(y_true, y_pred, odds),
    }

    return results
