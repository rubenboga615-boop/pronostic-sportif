"""Rapport de calibration du modèle."""

from evaluation.metrics import calibration_curve


def generate_calibration_report(
    y_true: list[int],
    y_prob: list[float],
    market: str,
) -> dict:
    """Générer un rapport de calibration."""
    curve = calibration_curve(y_true, y_prob)

    report = {
        "market": market,
        "n_observations": len(y_true),
        "calibration_curve": [{"predicted": p, "observed": o, "count": c} for p, o, c in curve],
    }

    # Calculer le miscalibration moyen
    if curve:
        miscalibration = sum(abs(p - o) for p, o, c in curve) / len(curve)
        report["mean_miscalibration"] = miscalibration

    return report
