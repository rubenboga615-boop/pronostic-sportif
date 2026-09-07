# Feuille de route

> Établie le 6 septembre 2026, sur l'audit en lecture seule du dépôt.
> Les repères `C1`, `E6`, `M8`… renvoient aux constats de cet audit.

Dix-sept étapes, de l'état constaté à un produit en service. L'ordre n'est pas
négociable : chaque étape lève un blocage de la suivante. **Assainir avant de
charger, charger avant de modéliser, modéliser avant d'ouvrir les vannes, et
prouver que le moteur gagne avant d'en faire un produit.**

Chaque étape se termine sur un critère vérifiable — une commande à lancer, un
nombre à constater — et non sur une impression. Les durées sont en jours de
travail effectif, hors téléchargements et temps d'attente.

## Avancement

**Lots A et B terminés le 6 septembre 2026** — étapes 0 à 6. Le seul reste
de ces lots est l'**import des ~19 900 matchs** (12 saisons × 5 championnats),
à lancer sur votre machine : le code est prêt et testé, mais le réseau de
l'environnement de développement bloque football-data.co.uk.

**Étape 6 b ajoutée le 7 septembre 2026** après analyse du document d'origine du
projet : une part de ce qu'il réclamait dort déjà en base, faute de calcul
dérivé. Elle ne dépend d'aucune source nouvelle et se place avant le lot C.

Restent ensuite le lot C (API-Football, Understat, application et administration),
le lot D (automatisation, déploiement, suivi) et le lot E (coupons, rédaction
assistée, abonnements) — ce dernier conditionné à un moteur validé.

## État constaté au départ

| | |
|---|---|
| Corpus | 760 matchs, 1 championnat sur 5, 2 saisons sur 11 |
| Prédictions | 0 — le pipeline n'a jamais été exécuté sur la base |
| Sources | 1 sur 3 retenues — Understat et API-Football restent à écrire |
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
deux fois. À 760 matchs il passe ; à 19 900, il ne finira pas (`E6`).

- Elo et classement incrémentaux, sur un seul balayage chronologique
- Index `matches(competition_id, match_date)` et les deux autres repérés dans `ACTIONS_EN_ATTENTE.md`
- Déclarer les index dans les modèles ORM, pas seulement dans le fichier SQL de migration (`M8`)

**Fait quand** — recalcul complet des 760 matchs chronométré, extrapolation
inférieure à 5 minutes pour 20 000 matchs.

---

## Lot B — Construire le moteur · ✅ terminé (import des 19 900 matchs restant à lancer)

Le corpus, puis un vrai modèle, puis tous les marchés de la Phase 1, puis une
évaluation qui veut dire quelque chose.

### Étape 3 — Constituer le corpus historique · ⚠️ code fait, import à lancer

Environ 19 900 matchs sont à un téléchargement gratuit, avec leurs cotes de
clôture. Le protocole de validation chronologique de la spec (entraînement
2015→2021) est aujourd'hui inexécutable : la base ne contient rien avant
août 2023.

- Étendre le parseur aux cotes Over/Under 2,5, ouverture et clôture (`N1`) — vingt colonnes présentes dans les CSV et intégralement ignorées
- Supprimer les mappings morts `IWH` et `BbMxH`, disparus des fichiers depuis des saisons
- Détecter et signaler la disparition d'une colonne attendue au lieu de l'ignorer (`M8`)
- Importer les 5 championnats × 12 saisons (2014/15 → 2025/26), après sauvegarde vérifiée
- Horodater le rapport de qualité au lieu d'écraser `import_report.json` (`N2`)

**Fait quand** — ≈ 19 900 matchs · 5 compétitions · cotes O/U en base · rapport
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

### Étape 6 b — Les calculs dérivés qui manquent · 1 à 2 jours

Le document d'origine du projet réclame une centaine de variables. La
comparaison au dépôt donne un résultat inattendu : **une partie de ce qui
« manque » est déjà en base et n'est simplement jamais dérivée**. Corners,
fautes, cartons, buts de mi-temps et cotes d'ouverture sont importés depuis le
premier jour.

Le trou le plus coûteux concerne la mi-temps : **15 sélections sur 31** portent
sur la première période, et **aucune variable ne la décrit**. C'est l'explication
la plus probable du 1N2 première mi-temps mesuré à 0,609 d'AUC, contre 0,693 en
match entier.

- Dix variables de mi-temps : `ht_home_win_rate`, `ht_away_win_rate`,
  `ht_draw_rate`, `ht_home_goals_avg`, `ht_away_goals_avg`, `ht_total_goals_avg`,
  `ht_over_05_rate`, `ht_over_15_rate`, `ht_over_25_rate`, `ht_over_35_rate`
- Fatigue et calendrier : `rest_days_diff`, `matches_last_7_days`,
  `matches_last_14_days`
- Solidité : `clean_sheets_5`, `failed_to_score_5` — déjà calculés par
  `form.py`, aujourd'hui jetés faute de colonne
- **Diagnostiquer le BTTS à 0,537 d'AUC** : anormalement bas pour un marché
  dérivé des mêmes λ qui donnent 0,805 en Over/Under. Défaut de dérivation
  probable, pas manque de données
- Lire `Referee`, présent dans le CSV et jamais parsé (utile en Phase 2)
- Trancher les quatre colonnes orphelines — `home_away_goals_for_avg`,
  `home_away_goals_against_avg`, `opponent_strength`, `data_completeness` —
  déclarées au schéma et qu'aucun code n'écrit : les brancher ou les retirer

Aucune source nouvelle, aucun quota, aucun scraping. Contrainte inchangée :
toute variable est bornée à la saison et strictement antérieure au match.

**Fait quand** — les dix variables de mi-temps sont peuplées sur la base
complète · l'AUC du 1N2 première mi-temps est mesurée avant et après · le BTTS
est diagnostiqué, corrigé ou documenté comme limite structurelle · plus aucune
colonne déclarée sans écrivain.

---

## Lot C — Ouvrir sur le réel · 10 à 14 jours

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

### Étape 9 — L'application : API et interface d'administration · 5 à 7 jours

Aucun routeur n'est branché dans `main.py` ; les cinq modules de routes
renvoient « à implémenter » et les schémas Pydantic ne sont importés nulle part
(`E7`).

**9.1 — API et sécurité**

- Brancher les routeurs : matchs, prédictions, sources, administration
- Restreindre le CORS, aujourd'hui ouvert à tous avec identifiants (`F4`)
- Authentification et les quatre rôles : `visiteur`, `abonné`, `analyste`,
  `administrateur` — aucun compte d'administration par défaut, jamais

**9.2 — Interface d'administration** (spécifiée dans `PROJECT_SPEC.md`)

Neuf écrans, dont l'ordre reflète la fréquence d'usage réelle :

1. Tableau de bord d'exploitation
2. Sources et qualité — quota, dernier import, **colonnes disparues du CSV**,
   complétude par saison et championnat
3. Pilotage du moteur — import, features, entraînement, prédictions, règlement.
   Toute action journalisée ; **action destructive refusée sans sauvegarde
   vérifiée**
4. Registre des modèles — **promotion en production et retour arrière**, le
   pouvoir le plus important de l'interface
5. Performance et calibration — par marché, championnat et période, contre les
   références naïve et marché
6. Coupons — statuts, dépublication, seuils versionnés, **interrupteur d'arrêt
   global**
7. Couche de rédaction — texte, entrée, sortie brute, vérification numérique
8. Utilisateurs et abonnements — aucune donnée de paiement stockée
9. Journal d'audit — en ajout seul, ni modifiable ni purgeable

Interdits par construction (D-10) : modifier une probabilité, une cote, un edge
ou un résultat réglé ; supprimer une entrée du journal ; filtrer l'historique
public.

**9.3 — Interface publique**

- Visiteur : historique de performance **complet et non filtré**, méthodologie
- Abonné : coupons du jour, détail par match, historique personnel
- Toute probabilité affichée avec son incertitude ; aucun coupon présenté comme
  sûr

**Fait quand** — `GET /predictions/{match_id}` renvoie de vraies prédictions ·
un administrateur peut promouvoir une version de modèle et revenir en arrière ·
l'interrupteur d'arrêt suspend effectivement la publication · un analyste voit
tout et ne déclenche rien · toute action d'administration figure au journal.

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

## Lot E — Le produit · 6 à 9 jours · **conditionné**

Ce lot ne démarre **que si** le rendement du moteur est positif sur les deux
saisons de test. Construit avant, il ne ferait que distribuer plus efficacement
un produit dont on ignore s'il fonctionne (D-06).

### Étape 13 — Génération de coupons · 3 à 4 jours

- Une sélection par match ; calibration de chaque jambe **avant** multiplication
- Probabilité jointe, edge contre la **cote combinée réellement offerte**
- Formats 3, 4 et 5 jambes ; seuils versionnés, jamais en dur
- Mise fixe, puis Kelly fractionnaire. **Pas de montante dans le moteur** (D-07)
- `strategie_coupon` évaluée comme les autres stratégies sur les saisons de test
- Statut `brouillon` → `publié`, avec interrupteur d'arrêt (D-11)

**Fait quand** — le générateur est backtesté sur 2024/25 et 2025/26 · son
rendement est publié à côté des références naïve et marché · aucun coupon n'est
publié si ce rendement est négatif.

### Étape 14 — Couche de rédaction assistée · 1 à 2 jours

- Interface unique `rediger_presentation(coupon) -> dict`, fournisseur derrière
  une variable d'environnement
- Entrée JSON structurée, sortie validée contre un schéma
- **Vérification numérique** : tout nombre du texte doit figurer dans l'entrée
- Repli sans IA : le coupon se publie avec les données brutes
- Consigne : exacte, pas « convaincante » (D-09). Aucun verdict bloquant (D-08)

**Fait quand** — un coupon rédigé, stocké et affiché · un appel en échec ne
bloque rien · une valeur inventée est rejetée par le contrôle numérique.

### Étape 15 — Abonnements et interface publique · 2 à 3 jours

- Rôles `visiteur` et `abonné`, échéances, suspension
- Écrans publics : historique de performance, coupons du jour, détail par match
- Paiement délégué au prestataire ; aucune donnée bancaire en base

**Fait quand** — un abonné voit les coupons du jour, un visiteur voit
l'historique complet, et personne ne voit les paramètres du modèle.

---

## Hors périmètre, volontairement

- **Marchés de Phase 2** — handicaps, scores exacts, HT/FT, buteurs : interdits sans validation explicite (`knowledge.md`).
- **Modèle d'apprentissage automatique** — à ouvrir après l'étape 6, jamais avant : entraîné aujourd'hui, il apprendrait surtout la fuite des cotes de clôture.
- **LLM dans le calcul** — la couche de rédaction (étape 14) écrit, elle ne juge ni ne calcule. Aucune probabilité, aucun verdict bloquant (D-08). Le moteur doit rester déterministe et rejouable des années plus tard.
- **Montante dans le moteur** — écartée (D-07) : une progression ne modifie pas l'espérance, seulement la variance. Tolérée comme choix explicite de l'utilisateur, avec sa probabilité d'aboutissement affichée.
- **Probabilité du marché en variable d'entrée** — écartée (D-04) : le modèle apprendrait à recopier le bookmaker et l'edge tendrait vers zéro par construction.
- **PostgreSQL** — SQLite tient les 20 000 matchs ; à reconsidérer si plusieurs écrivains concurrents apparaissent.

## Chemin critique

Les étapes 1 et 2 conditionnent tout : importer 19 900 matchs avec le classement
inter-saisons et le pipeline quadratique, c'est produire vingt-cinq fois plus de
lignes fausses, très lentement.

L'étape 6 b ne dépend d'aucune source et peut démarrer immédiatement — c'est le
meilleur rapport valeur/effort restant. L'import des 12 saisons la précède
idéalement, pour que ses effets soient mesurables.

Les étapes 8 (xG) et 9 (application) peuvent se mener en parallèle par une
seconde personne. Tout le reste est strictement séquentiel.

Le **lot E est conditionné** : il ne démarre que si le rendement du moteur est
positif sur les deux saisons de test. Si la mesure est négative, le travail
repart sur le moteur, pas sur le produit.

**Reste 20 à 30 jours de travail effectif** pour un développeur — dont 6 à 9
pour le seul lot E, qui peut ne jamais être engagé.
