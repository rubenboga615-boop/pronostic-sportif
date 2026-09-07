# Feuille de route

> Établie le 6 septembre 2026, sur l'audit en lecture seule du dépôt.
> Les repères `C1`, `E6`, `M8`… renvoient aux constats de cet audit.

Treize étapes, de l'état constaté à un moteur qui tourne seul en production.
L'ordre n'est pas négociable : chaque étape lève un blocage de la suivante.
**Assainir avant de charger, charger avant de modéliser, modéliser avant
d'ouvrir les vannes.**

Chaque étape se termine sur un critère vérifiable — une commande à lancer, un
nombre à constater — et non sur une impression. Les durées sont en jours de
travail effectif, hors téléchargements et temps d'attente.

## Avancement

**Lots A et B terminés le 6 septembre 2026** — étapes 0 à 6. Le seul reste
de ces lots est l'**import des ~19 000 matchs**, à lancer sur votre machine :
le code est prêt et testé, mais le réseau de l'environnement de développement
bloque football-data.co.uk.

Reste le lot C (API-Football, Understat, application) et le lot D
(automatisation, déploiement, suivi).

## État constaté au départ

| | |
|---|---|
| Corpus | 760 matchs, 1 championnat sur 5, 2 saisons sur 11 |
| Prédictions | 0 — le pipeline n'a jamais été exécuté sur la base |
| Sources | 1 sur 4 — Understat, API-Football et The Odds API restent à écrire |
| Tests | 211 sur 214 au départ, 226 en local non commités |

---

## Lot A — Assainir · ✅ terminé

Rien de ce qui suit n'a de valeur tant que les données produites sont fausses.
Ce lot ne crée aucune fonctionnalité : il rend fiable ce qui existe déjà, et
rapide ce qui devra encaisser vingt-cinq fois plus de données.

### Étape 0 — Sécuriser le travail existant · ✅ fait le 06/09/2026

Le correctif `reference_date`, qui empêche le pipeline de re-prédire tout
l'historique chaque jour, n'existait qu'en local, sans sauvegarde versionnée.

- [x] Committer le correctif `reference_date` et ses douze tests
- [x] Rendre hermétiques les trois tests `TestOriginalDatabaseUntouched`, qui exigeaient `data/pronostic.db` (`M7`)
- [x] Repartir de zéro violation `ruff`, sans quoi un contrôle de style n'a aucune valeur
- [x] Rendre le paquet installable : backend de build et dépendances manquantes (`F1`)
- [x] Intégration continue : `pytest` et `ruff` à chaque poussée (`M8`)
- [x] Actualiser `docs/ETAT_ACTUEL.md` (`F7`)

**Fait quand** — CI verte sur la branche · `pytest -q` vert sur un clone neuf,
sans base de production.

### Étape 1 — Purger les défauts qui corrompent les données · ✅ fait le 06/09/2026

Trois colonnes de `features` sont inexploitables : deux fausses, une contaminée.
Charger davantage de données avant ce correctif ne fait que multiplier les
lignes à jeter.

- Borner le classement, l'Elo et les jours de repos à la saison en cours (`C2`) — Arsenal démarre aujourd'hui 2024/25 à la 2ᵉ place avec +62 de différence de buts, et `MAX(league_position)` vaut 23 dans un championnat à 20 équipes
- Retirer `odds_movement` des features persistées et horodater distinctement les cotes d'ouverture et de clôture (`C1`) — la colonne est remplie à 100 % et corrèle avec le résultat du match
- Écrire le vrai test anti-fuite : collecter les dates réellement consommées, échouer si l'une atteint la date du match (`C4`) — c'est le garde-fou qui aurait attrapé `C1` et `C2`
- Corriger la moyenne de buts, qui divise par la fenêtre au lieu des matchs effectivement notés (`M3`)
- Normaliser la matrice de scores pour que les probabilités somment à 1 (`M2`)
- Poser les contraintes d'unicité manquantes sur `features`, `predictions` et `matches` (`E8`)

**Fait quand** — test anti-fuite au vert · `MAX(league_position) <= 20` ·
`odds_movement IS NULL` partout · somme des probabilités 1N2 = 1 ± 1e-9.

### Étape 2 — Rendre le calcul de features linéaire · ✅ fait le 06/09/2026

Le pipeline rejoue toute la boucle Elo et tout le classement pour chaque match,
deux fois. À 760 matchs il passe ; à 19 000, il ne finira pas (`E6`).

- Elo et classement incrémentaux, sur un seul balayage chronologique
- Index `matches(competition_id, match_date)` et les deux autres repérés dans `ACTIONS_EN_ATTENTE.md`
- Déclarer les index dans les modèles ORM, pas seulement dans le fichier SQL de migration (`M8`)

**Fait quand** — recalcul complet des 760 matchs chronométré, extrapolation
inférieure à 5 minutes pour 20 000 matchs.

---

## Lot B — Construire le moteur · ✅ terminé (import des 19 000 matchs restant à lancer)

Le corpus, puis un vrai modèle, puis tous les marchés de la Phase 1, puis une
évaluation qui veut dire quelque chose.

### Étape 3 — Constituer le corpus historique · ⚠️ code fait, import à lancer

Environ 19 000 matchs sont à un téléchargement gratuit, avec leurs cotes de
clôture. Le protocole de validation chronologique de la spec (entraînement
2015→2021) est aujourd'hui inexécutable : la base ne contient rien avant
août 2023.

- Étendre le parseur aux cotes Over/Under 2,5, ouverture et clôture (`N1`) — vingt colonnes présentes dans les CSV et intégralement ignorées
- Supprimer les mappings morts `IWH` et `BbMxH`, disparus des fichiers depuis des saisons
- Détecter et signaler la disparition d'une colonne attendue au lieu de l'ignorer (`M8`)
- Importer les 5 championnats × 11 saisons, après sauvegarde vérifiée
- Horodater le rapport de qualité au lieu d'écraser `import_report.json` (`N2`)

**Fait quand** — ≈ 19 000 matchs · 5 compétitions · cotes O/U en base · rapport
de qualité archivé.

### Étape 4 — Le moteur de buts, pour de vrai · ✅ fait le 06/09/2026

L'actuel `fit_dixon_coles` n'entraîne rien : il renvoie deux moyennes globales
et un rho heuristique. La log-vraisemblance et `scipy.optimize` sont écrits mais
jamais appelés (`E1`).

- Estimation par maximum de vraisemblance : forces d'attaque et de défense par équipe, avantage du terrain, rho
- Pondération temporelle des matchs anciens
- Dériver les lambdas des forces d'équipe plutôt que de moyennes glissantes brutes
- Modèle de première mi-temps sur `HTHG` / `HTAG`
- Brancher `model_registry`, écrit mais jamais utilisé : chaque modèle versionné et rejouable

**Fait quand** — Dixon-Coles entraîné sur 2015→2021 · log-loss et Brier comparés
au Poisson sur la saison de validation · modèle enregistré et rechargeable.

### Étape 5 — Compléter les marchés de la Phase 1 · ✅ fait le 06/09/2026

Les marchés de mi-temps sont dérivables mais ne sont ni assemblés ni
persistables : `persist_predictions` les rejetterait. Le README les annonce
pourtant comme livrés (`E3`).

- Assembler 1N2, double chance et Over/Under de première mi-temps
- Assembler la mi-temps la plus prolifique
- Étendre le contrat public `PUBLIC_MARKETS` et ses tests
- Isoler `derive_asian_handicap`, marché de Phase 2 présent sans validation

**Fait quand** — ≈ 30 sélections persistées par match au lieu de 16 · README
aligné sur le réel.

### Étape 6 — Boucler la boucle : résultats et évaluation · ✅ fait le 06/09/2026

La table `actual_results` n'est écrite nulle part et le ROI est calculé contre
les cotes du modèle lui-même — une tautologie. Sans cette étape, aucune des onze
questions de la définition de réussite n'a de réponse (`C3`, `M1`).

- Régler chaque marché depuis le score final : alimenter `actual_results`
- Calculer `offered_odds` et `edge` depuis `odds_snapshots`
- Ajouter `data_cutoff_at` et `source_versions` aux prédictions, exigés par la spec
- Réparer le backtest : cote offerte, sélection la plus probable, résultats par championnat, par saison et par tranche de cote
- Calibration réelle (Platt ou isotone) à la place du substitut qui renvoie ses entrées
- Comparaison obligatoire : contre le marché, et contre une stratégie naïve

**Fait quand** — rapport de backtest chronologique complet · courbe de
calibration par marché · ROI mesuré contre les cotes de clôture.

---

## Lot C — Ouvrir sur le réel · 8 à 11 jours

Jusqu'ici, le système ne sait rien des matchs à venir. Ce lot le connecte au
présent, puis rend le tout consultable.

### Étape 7 — API-Football : le calendrier et les absents · 3 à 4 jours

Si la table `predictions` est vide, ce n'est pas à cause du modèle : la base ne
contient aucun match futur. Le plan Pro offre 7 500 requêtes par jour, là où 200
à 500 suffisent pour cinq championnats.

- Écrire `client.py`, `endpoints.py`, `quota.py` avec cache disque et respect des quotas
- **Table de correspondance d'équipes entre fournisseurs**, générée hors ligne, relue et commitée — sans elle, l'import duplique les 23 équipes et scinde tout l'historique
- Calendrier des matchs à venir : des matchs futurs enfin en base
- Blessures et suspensions vers `availability`, avec la règle : absence d'information ≠ absence de blessure
- Cotes pré-match vers `offered_odds` et `edge` sur les matchs à venir
- Alimenter `source_health`, dont `quota_remaining`

**Fait quand** — des matchs de la semaine à venir en base · des prédictions
générées dessus · quota suivi et journalisé.

### Étape 8 — Understat : le xG · 2 à 3 jours

Trois colonnes de features attendent cette source depuis le début. API-Football
ne la remplace pas de façon fiable.

- Client, parseur et limiteur de débit, avec cache obligatoire et conservation des données brutes
- Correspondance d'équipes, à ajouter à la table de l'étape 7
- Corriger le filtre anti-fuite, qui compare la date de collecte et non la date du match (`M6`)

**Fait quand** — `xg_match_stats` peuplé · features xG non nulles · backtest
comparé avec et sans Understat.

### Étape 9 — L'application : API et tableau de bord · 3 à 4 jours

Aucun routeur n'est branché dans `main.py` ; les cinq modules de routes
renvoient « à implémenter » et les schémas Pydantic ne sont importés nulle part
(`E7`).

- Brancher les routeurs et implémenter matchs, prédictions, sources et administration sur les schémas existants
- Restreindre le CORS, aujourd'hui ouvert à tous avec identifiants (`F4`)
- Connecter le tableau de bord : matchs à venir, prédictions du jour, qualité des données, historique, métriques

**Fait quand** — `GET /predictions/{match_id}` renvoie de vraies prédictions ·
le tableau de bord n'affiche plus un seul écran vide.

---

## Lot D — Exploiter · 3 à 5 jours, puis en continu

### Étape 10 — Automatiser la journée type · 2 à 3 jours

Six des huit étapes de la mise à jour quotidienne sont des `pass`, dont la
sauvegarde — pourtant classée non négociable (`E4`).

- Implémenter réellement les huit étapes, de la collecte à la sauvegarde
- Alerter en cas d'échec, au lieu d'avaler l'exception dans le journal
- Collecte à 48 h du match : rafraîchir absences et cotes, régénérer une prédiction **en conservant la précédente**
- Brancher les scripts sur les pipelines : `make collect`, `make predict` et `make train` ne font rien aujourd'hui

**Fait quand** — une exécution quotidienne complète, idempotente, avec
sauvegarde horodatée et rapport · deux exécutions de suite ne créent aucun
doublon.

### Étape 11 — Déployer · 1 à 2 jours

L'image actuelle ne peut pas passer son propre contrôle de santé : il appelle
`curl`, absent de l'image *slim* (`F3`).

- Corriger le contrôle de santé, ajouter un `.dockerignore`, exécuter en utilisateur non privilégié
- Ordonnancer la mise à jour quotidienne selon `PIPELINE_DAILY_HOUR`
- Volumes persistants, sauvegardes hors conteneur, rotation
- Journalisation et supervision : exposer `source_health`
- Documentation de déploiement et procédure de restauration

**Fait quand** — machine cible relancée à froid : conteneurs sains, pipeline
quotidien qui s'exécute seul, restauration testée depuis une sauvegarde.

### Étape 12 — Suivre, mesurer, décider · en continu

La spec fixe le vrai critère de fin : pouvoir répondre objectivement à onze
questions au bout d'un an.

- Revue hebdomadaire : calibration, ROI contre les cotes de clôture, stabilité par championnat
- Rapport de stabilité et journal des sources
- Performances mesurées sans Understat, sans blessures, et contre le marché
- Ne pas déclarer la rentabilité sur une saison en cours
- Décider, sur preuve hors échantillon, d'adopter ou non le modèle d'apprentissage automatique

**Fait quand** — les onze questions de la définition de réussite ont chacune une
réponse chiffrée et datée.

---

## Hors périmètre, volontairement

- **Marchés de Phase 2** — handicaps, scores exacts, HT/FT, buteurs : interdits sans validation explicite (`knowledge.md`).
- **Modèle d'apprentissage automatique** — à ouvrir après l'étape 6, jamais avant : entraîné aujourd'hui, il apprendrait surtout la fuite des cotes de clôture.
- **LLM dans l'application** — utile pour la table de correspondance d'équipes (hors ligne) et l'explication des prédictions ; jamais dans le calcul des probabilités, qui doit rester déterministe et rejouable.
- **PostgreSQL** — SQLite tient les 20 000 matchs ; à reconsidérer si plusieurs écrivains concurrents apparaissent.

## Chemin critique

Les étapes 1 et 2 conditionnent tout : importer 19 000 matchs avec le classement
inter-saisons et le pipeline quadratique, c'est produire vingt-cinq fois plus de
lignes fausses, très lentement.

Les étapes 8 (xG) et 9 (application) peuvent se mener en parallèle par une
seconde personne. Tout le reste est strictement séquentiel.

**21 à 32 jours de travail effectif** pour un développeur, soit six à huit
semaines à mi-temps.
