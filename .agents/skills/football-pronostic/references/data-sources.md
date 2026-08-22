# Sources de données

## Football-Data.co.uk

**Usage :**

- Résultats historiques
- Résultats à la mi-temps
- Statistiques disponibles
- Cotes historiques

**Contrôles :**

- Vérifier les colonnes par saison
- Gérer les colonnes absentes
- Détecter les doublons
- Conserver le fichier original
- Enregistrer la date de téléchargement

## Understat

**Usage :**

- xG, xGA, NPxG, xA
- Tirs et qualité des tirs

**Contrôles :**

- Mettre en cache
- Limiter les requêtes
- Vérifier la saison et la ligue
- Ne pas supposer une couverture complète
- Signaler les données indisponibles

## API-Football

**Usage :**

- Calendriers et événements
- Classements et statistiques
- Blessures et compositions
- Cotes disponibles

**Contrôles :**

- Suivre le quota (100 req/jour en gratuit)
- Éviter les appels répétés
- Sauvegarder les réponses
- Vérifier les identifiants d'équipes
- Gérer les réponses vides

## The Odds API

**Usage :**

- Compléter les cotes actuelles
- Capturer plusieurs snapshots

**Contrôles :**

- Suivre les crédits (500/mois en gratuit)
- Limiter les marchés
- Enregistrer la région et le bookmaker
- Ne pas confondre cote actuelle et cote de clôture
