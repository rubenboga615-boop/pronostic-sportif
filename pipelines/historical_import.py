"""Pipeline d'import des données historiques."""

from loguru import logger


def run_historical_import() -> None:
    """Exécuter le pipeline d'import historique.
    
    Étapes :
    1. Télécharger les CSV des cinq championnats
    2. Normaliser les noms d'équipes
    3. Normaliser les dates
    4. Charger les résultats finaux et mi-temps
    5. Ajouter la déduplication
    6. Produire un rapport de qualité
    """
    logger.info("=== Début de l'import historique ===")

    # Étape 1 : Téléchargement
    logger.info("Étape 1 : Téléchargement des CSV...")
    # TODO: implémenter avec collectors.football_data.downloader

    # Étape 2 : Normalisation
    logger.info("Étape 2 : Normalisation des noms d'équipes...")
    # TODO: implémenter

    # Étape 3 : Parse et nettoyage
    logger.info("Étape 3 : Parse et nettoyage des dates...")
    # TODO: implémenter avec collectors.football_data.parser

    # Étape 4 : Chargement en base
    logger.info("Étape 4 : Chargement en base de données...")
    # TODO: implémenter

    # Étape 5 : Déduplication
    logger.info("Étape 5 : Déduplication...")
    # TODO: implémenter

    # Étape 6 : Rapport de qualité
    logger.info("Étape 6 : Rapport de qualité...")
    # TODO: implémenter

    logger.info("=== Fin de l'import historique ===")


if __name__ == "__main__":
    run_historical_import()
