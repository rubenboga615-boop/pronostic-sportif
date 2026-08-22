.PHONY: install dev test lint format run dashboard import backup help

help: ## Afficher cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Installer les dépendances
	pip install -r requirements.txt

dev: ## Installer les dépendances dev
	pip install -e ".[dev,ml,scraping]"

test: ## Exécuter les tests
	pytest tests/ -v

test-cov: ## Exécuter les tests avec couverture
	pytest tests/ -v --cov=. --cov-report=html

lint: ## Vérifier le code avec ruff
	ruff check .

format: ## Formatter le code avec ruff
	ruff format .

run: ## Lancer l'API
	uvicorn app.main:app --reload

dashboard: ## Lancer le dashboard
	streamlit run dashboard/streamlit_app.py

import: ## Importer les données historiques
	python scripts/import_historical_data.py

collect: ## Collecte quotidienne
	python scripts/collect_daily.py

predict: ## Générer les prédictions
	python scripts/generate_predictions.py

train: ## Entraîner les modèles
	python scripts/train_models.py

backup: ## Créer une sauvegarde
	python scripts/create_backup.py

docker-up: ## Lancer avec Docker
	docker-compose up -d

docker-down: ## Arrêter Docker
	docker-compose down

docker-build: ## Construire les images Docker
	docker-compose build
