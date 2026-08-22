# Validation

## Séparation chronologique

Utiliser une séparation chronologique. Ne jamais mélanger les matchs futurs dans l'entraînement.

```text
Entraînement  : saisons 2015/16 à 2021/22
Validation    : saison 2022/23
Test          : saison 2023/24
Test récent   : saison 2024/25
```

## Métriques minimales

Pour chaque marché :

- Log loss
- Brier score
- Calibration
- Accuracy
- ROI simulé
- Drawdown maximal
- Nombre d'observations

## Comparaisons obligatoires

Comparer :

- Modèle proposé
- Marché implicite (cotes normalisées)
- Stratégie naïve (toujours favori)
- Modèle sans xG
- Modèle sans blessures
- Modèle sans cotes

## Rapports

Rapporter les résultats par :

- Championnat
- Saison
- Marché
- Tranche de probabilité
- Tranche de cote

## Règles

- Ne jamais présenter uniquement l'accuracy
- Un modèle qui prédit souvent l'issue favorite peut avoir une bonne précision mais être non rentable après la marge du bookmaker
- Ne pas utiliser la saison en cours pour déclarer la rentabilité avant qu'elle soit terminée
