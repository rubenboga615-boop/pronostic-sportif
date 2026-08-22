"""Génération de rapports d'évaluation."""

from loguru import logger


def generate_full_report(
    backtest_results: list[dict],
    output_dir: str = "data/exports",
) -> dict:
    """Générer un rapport complet d'évaluation."""
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    report = {
        "total_markets": len(backtest_results),
        "results_by_market": {},
    }

    for result in backtest_results:
        market = result.get("market", "unknown")
        report["results_by_market"][market] = {
            "n_matches": result.get("n_matches", 0),
            "accuracy": result.get("accuracy", 0),
            "brier_score": result.get("brier_score", 0),
            "roi": result.get("roi", {}),
        }

    # Sauvegarder en JSON
    import json
    report_file = output_path / "evaluation_report.json"
    report_file.write_text(json.dumps(report, indent=2, default=str))
    logger.info(f"Rapport sauvegardé : {report_file}")

    return report
