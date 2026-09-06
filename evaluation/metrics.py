"""Métriques d'évaluation du modèle de pronostic."""

import numpy as np


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    """Calculer l'accuracy."""
    if not y_true:
        return 0.0
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true)


def log_loss(y_true: list[int], y_prob: list[float], epsilon: float = 1e-15) -> float:
    """Calculer la log loss (cross-entropy)."""
    y_prob = np.clip(y_prob, epsilon, 1 - epsilon)
    y_true = np.array(y_true)
    y_prob = np.array(y_prob)
    return -np.mean(y_true * np.log(y_prob) + (1 - y_true) * np.log(1 - y_prob))


def brier_score(y_true: list[int], y_prob: list[float]) -> float:
    """Calculer le Brier score (erreur quadratique moyenne)."""
    y_true = np.array(y_true, dtype=float)
    y_prob = np.array(y_prob, dtype=float)
    return float(np.mean((y_true - y_prob) ** 2))


def calibration_curve(
    y_true: list[int],
    y_prob: list[float],
    n_bins: int = 10,
) -> list[tuple[float, float, int]]:
    """Calculer la courbe de calibration.

    Retourne une liste de (probabilité prédite, probabilité observée, nombre d'observations).
    """
    bins = np.linspace(0, 1, n_bins + 1)
    results = []

    for i in range(n_bins):
        mask = (np.array(y_prob) >= bins[i]) & (np.array(y_prob) < bins[i + 1])
        if mask.sum() > 0:
            mean_predicted = float(np.mean(np.array(y_prob)[mask]))
            mean_observed = float(np.mean(np.array(y_true)[mask]))
            results.append((mean_predicted, mean_observed, int(mask.sum())))

    return results


def roi_simulation(
    y_true: list[str],
    y_pred: list[str],
    odds: list[float],
    stake: float = 1.0,
) -> dict:
    """Simuler le ROI (Return on Investment)."""
    total_stake = 0.0
    total_return = 0.0
    max_drawdown = 0.0
    current_balance = 0.0
    peak = 0.0
    bets_count = 0

    for true, pred, odd in zip(y_true, y_pred, odds):
        if odd <= 1.0:
            continue

        total_stake += stake
        bets_count += 1

        if true == pred:
            total_return += stake * odd
            current_balance += stake * (odd - 1)
        else:
            current_balance -= stake

        peak = max(peak, current_balance)
        drawdown = peak - current_balance
        max_drawdown = max(max_drawdown, drawdown)

    roi = ((total_return - total_stake) / total_stake * 100) if total_stake > 0 else 0.0

    return {
        "total_stake": total_stake,
        "total_return": total_return,
        "profit": total_return - total_stake,
        "roi_pct": roi,
        "max_drawdown": max_drawdown,
        "bets_count": bets_count,
    }
