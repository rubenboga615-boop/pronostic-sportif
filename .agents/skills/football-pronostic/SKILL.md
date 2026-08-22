---
name: football-pronostic
description: Développer, tester et maintenir un moteur probabiliste de pronostic football sur cinq grands championnats, avec collecte multi-source, prévention des fuites de données et évaluation chronologique.
license: MIT
metadata:
  domain: sports-analytics
  phase: phase-1
---

# Skill Football Pronostic

## Avant toute action

Lire obligatoirement :

- PROJECT_SPEC.md
- knowledge.md
- references/data-sources.md
- references/markets.md
- references/validation.md

Vérifier la Phase active avant d'ajouter une fonctionnalité.

## Mission

Construire un moteur probabiliste, pas un système de certitudes.
Les sorties doivent être des probabilités, des cotes équitables,
un niveau de qualité des données et une version de modèle.

## Marchés actifs

**Match entier :**

- 1N2
- Double chance
- Over/Under 0.5, 1.5, 2.5, 3.5
- BTTS
- Mi-temps la plus prolifique

**Première mi-temps :**

- 1N2
- Double chance
- Over/Under

## Marchés interdits pour l'instant

Ne pas implémenter sans validation explicite :

- Handicaps
- Scores exacts comme recommandation principale
- HT/FT
- Premier buteur
- Façon de marquer
- Pénalty

## Sources

- Utiliser Football-Data.co.uk pour l'historique
- Utiliser Understat pour xG et xGA lorsqu'une donnée valide existe
- Utiliser API-Football pour les informations récentes
- Utiliser The Odds API uniquement selon le quota disponible

Ne jamais considérer une réponse vide comme zéro.
Ne jamais remplacer une donnée inconnue par une absence confirmée.
Conserver source, horodatage et qualité de chaque donnée.

## Modélisation

Le moteur doit estimer :

- lambda_home
- lambda_away
- lambda_home_first_half
- lambda_away_first_half

Générer ensuite une matrice de scores.
Dériver les marchés depuis cette matrice afin de garder
des probabilités cohérentes.

Tester :

- Poisson
- Dixon-Coles
- Régression logistique
- XGBoost ou modèle équivalent si justifié

## Prévention des fuites

Avant la date et l'heure de prédiction, seules les données déjà connues
peuvent être utilisées.

Interdire :

- Cotes de clôture pour une prédiction pré-match générée plus tôt
- Score final
- Statistiques du match prédit
- Classement recalculé avec des matchs futurs
- Blessures annoncées après l'heure de prédiction

Ajouter un test automatique anti-fuite.

## Procédure de développement

Pour chaque demande :

1. Lire la spécification
2. Analyser les fichiers existants
3. Proposer un plan court
4. Modifier le minimum de fichiers nécessaire
5. Écrire ou mettre à jour les tests
6. Exécuter les tests
7. Vérifier les logs et les données
8. Résumer les modifications
9. Attendre validation avant de passer à une phase supérieure

## Gestion des sources

Chaque collecteur doit avoir :

- timeout
- retries
- backoff
- cache
- validation du schéma
- journalisation
- statut de santé
- sauvegarde de la réponse brute

Si la source échoue :

- Conserver le dernier snapshot valide
- Marquer les données comme anciennes
- Ne pas supprimer les données existantes
- Utiliser le modèle de secours
- Produire une alerte

## Format de sortie

Chaque prédiction doit contenir :

- match_id
- marché
- sélection
- probabilité
- cote équitable
- cote observée
- edge
- modèle
- version
- date de génération
- heure limite des données
- qualité des données
- variables manquantes
- statut

Ne jamais écrire « pari sûr », « gain garanti » ou « certitude ».
