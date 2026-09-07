# État actuel du projet

> Fichier de référence à lire en premier. Tenir à jour après chaque session.
> Dernière mise à jour : 2026-09-07.

## Projet
Moteur de pronostic football (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).

## État Git
- Branche : `claude/audit-lecture-seule-s5yd7b`
- Working tree : **propre**
- Suite de tests : **396 réussis, 3 ignorés** (les tests ignorés sont les
  garde-fous anti-production, actifs uniquement si `data/pronostic.db` existe)
- Sans l'extra `ml` : **392 réussis, 7 ignorés** — les quatre tests de
  calibration s'ignorent faute de scikit-learn, et c'est voulu. Le noyau
  (import, features, entraînement, prédiction, règlement, backtest) n'en a pas
  besoin. Pour les exécuter : `pip install -e ".[ml]"`.
- Style : **zéro violation `ruff`**, vérifié en intégration continue
- Avertissements : **zéro** (les 2 914 dépréciations `datetime.utcnow()` sont
  corrigées)

## Feuille de route
`docs/ROADMAP.md`. **Lots A et B terminés (étapes 0 à 6.)**

Prochaine étape de code : **6 b — les calculs dérivés qui manquent**, dont les
dix variables de mi-temps. Elle ne dépend d'aucune source nouvelle.

Restent le lot C (API-Football, Understat, API et interface d'administration),
le lot D (automatisation, déploiement, suivi) et le lot E (coupons, rédaction
assistée, abonnements) — ce dernier **conditionné** à un rendement positif
mesuré sur les deux saisons de test.

Décisions et motifs : `docs/DECISIONS.md`.

## Ce qui fonctionne de bout en bout
Import → features → entraînement → prédiction → règlement → valorisation →
backtest. Vérifié sur les données réelles : 760 matchs importés avec leurs
cotes Over/Under, modèle entraîné sur 2023/24, 10 160 prédictions générées et
réglées sur 2024/25, rapport de backtest complet.

## Première évaluation hors échantillon
Modèle Dixon-Coles entraîné sur 2023/24, appliqué aux 380 matchs de 2024/25 :

| Marché | Accuracy | Log-loss | Brier | AUC | ROI |
|---|---|---|---|---|---|
| 1N2 | 0,508 | 0,590 | 0,201 | 0,693 | −3,16 % |
| Over/Under | 0,721 | 0,539 | 0,182 | 0,805 | −2,16 % |
| 1N2 1re mi-temps | 0,393 | 0,621 | 0,215 | 0,609 | — |
| BTTS | 0,518 | 0,735 | 0,266 | 0,537 | — |

Références : pari naïf sur le domicile **−16,60 %**, favori du marché
**−3,56 %**. Le modèle bat nettement la stratégie naïve et se tient au niveau
du marché, sur une seule saison d'entraînement.

Sa courbe de calibration montre un excès de confiance dans le haut du spectre
(annoncé 0,84 → observé 0,67) : c'est ce que la calibration doit corriger, une
fois qu'il y aura une saison de validation distincte.

## Travaux terminés
- **Foreign keys SQLite**, **index déclarés dans l'ORM** et **contraintes
  d'unicité** sur les clés logiques de `features`, `predictions`, `matches` et
  `actual_results`.
- **Import Football-Data** : parse, normalisation, déduplication, cotes 1N2 et
  Over/Under 2,5 (ouverture et clôture), détection des colonnes disparues,
  rapport de qualité horodaté.
- **Téléchargeur** : réessais réellement opérants sur erreur transitoire,
  écriture atomique, refus des réponses vides.
- **Pipeline de features** : contexte incrémental, coût par match indépendant
  de la taille de la base (~17 ms, soit ~5 min pour 20 000 matchs).
- **Anti-fuite** : classement, Elo et repos bornés à la saison ; mouvement de
  cote étanche par construction ; test anti-fuite par historique empoisonné et
  mouchard de dates.
- **Dixon-Coles** entraîné par maximum de vraisemblance, avec pondération
  temporelle, ajusté par compétition, enregistré dans le registre des modèles.
- **Marchés** : 31 sélections par match (match entier + première mi-temps +
  mi-temps la plus prolifique).
- **Règlement, valorisation, backtest, calibration** : la boucle est fermée.
- **Intégration continue** : `ruff check`, `ruff format --check` et `pytest`
  sur Python 3.11 et 3.12, plus un job qui installe le noyau seul et vérifie
  que la suite reste verte sans les extras.

## Migrations à appliquer sur la base de production
À exécuter dans cet ordre, **après sauvegarde vérifiée** :

1. `migrations/20260906_purge_odds_movement.sql` — efface les 1 520 valeurs
   contaminées par les cotes de clôture, remet à NULL l'horodatage des cotes
   d'ouverture. Testée sur une copie, idempotente.
2. `migrations/20260906_add_unique_indexes.sql` — contraintes d'unicité et
   index manquants. Vérifier d'abord l'absence de doublons (requêtes fournies
   en tête de fichier).
3. `migrations/20260906_add_prediction_traceability.sql` — colonnes
   `data_cutoff_at` et `source_versions`. À n'exécuter qu'une fois.

Puis **recalculer les features** (`python -m pipelines.feature_pipeline`) :
le classement, l'Elo et les jours de repos actuellement en base ont été
calculés avec les défauts corrigés depuis.

## Prochaine action
**Importer les 5 championnats × 12 saisons** (2014/15 → 2025/26) :

```bash
cp data/pronostic.db data/backups/pronostic_avant_import_complet.db
python scripts/import_historical_data.py
```

Le code est prêt et testé ; le réseau de l'environnement de développement
bloque football-data.co.uk, l'import doit donc être lancé depuis votre machine.
Le protocole de validation actualisé (entraînement 2015/16 → 2022/23, validation
2023/24, test 2024/25 et 2025/26) reste inexécutable tant que la base s'arrête à
août 2023.

Ensuite : `python scripts/train_models.py` puis le pipeline de prédiction.

## Blocages / données indisponibles
- **xG** : `xg_match_stats` vide, collecteur Understat non écrit (étape 8).
- **Blessures** : `availability` vide, collecteur API-Football non écrit (étape 7).
- **Matchs à venir** : aucune source de calendrier, d'où l'absence de
  prédictions sur des matchs non joués (étape 7).
- **`odds_movement`** : restera `None` tant qu'aucune source ne fournira
  plusieurs relevés pré-match horodatés. C'est volontaire.
- `requirements.txt` épingle des versions inexistantes sur PyPI (numpy 2.5.2) :
  `make install` échoue. La CI installe depuis `pyproject.toml`.
- Convention de nommage `B365_close` / `PS_close` dans la colonne `bookmaker` :
  `is_closing` porte déjà l'information, ce doublon est à nettoyer un jour.

## Sauvegardes
- `data/backups/pronostic_avant_import_E0_2324.db`, `pronostic_avant_import_E0_2425.db`,
  `pronostic_avant_migration_aliases.db`, `pronostic_avant_migration_ipswich.db`
- `data/pronostic.db.before-features-20260823-2029.bak`
- `data/pronostic.db.before-odds-movement-fix-20260823-2247.bak`

## Règles de sécurité (non négociables)
- Ne jamais modifier la base sans sauvegarde préalable vérifiée.
- Ne jamais lancer d'import sans confirmation explicite.
- Toujours exécuter `python -m pytest -q` avant et après toute modification.
- Ne pas implémenter les marchés de Phase 2 sans validation (voir `knowledge.md`).
- Ne publier aucun coupon tant que le rendement n'est pas positif sur les deux
  saisons de test (`docs/DECISIONS.md`, D-06).
- Ne jamais modifier une probabilité, une cote, un edge ou un résultat réglé
  hors migration versionnée (D-10).
- Créer un commit séparé par action ; ne jamais committer sans demande explicite.
- Arrêter immédiatement au premier test échoué et afficher l'erreur complète.
- Respecter la règle anti-fuite : aucune donnée future dans les features.
