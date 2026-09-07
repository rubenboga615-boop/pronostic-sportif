-- Migration : variables de première mi-temps, calendrier et solidité (2026-09-07)
--
-- ⚠️ SAUVEGARDE OBLIGATOIRE AVANT EXÉCUTION.
--     cp data/pronostic.db data/backups/pronostic_avant_mi_temps.db
--     sqlite3 data/backups/pronostic_avant_mi_temps.db "PRAGMA integrity_check;"
--
-- Contexte
-- --------
-- Quinze des trente et une sélections produites par match portent sur la
-- première période — 1N2, double chance, over/under de mi-temps, mi-temps la
-- plus prolifique. Aucune variable ne la décrivait.
--
-- C'est l'explication la plus probable de l'écart mesuré entre le 1N2 de
-- mi-temps (0,609 d'AUC) et celui du match entier (0,693) : le modèle prédisait
-- la mi-temps sans rien savoir du comportement des équipes en première période.
--
-- Les données étaient en base depuis le premier import — `HTHG` et `HTAG` sont
-- lues par le parseur Football-Data et écrites dans `matches`. Seuls le
-- transport et le calcul dérivé manquaient.
--
-- Trois familles de colonnes sont ajoutées à `features` :
--
--   1. Première mi-temps (10 colonnes) — taux de domination séparés par lieu,
--      moyennes de buts, franchissement des quatre lignes over/under.
--
--   2. Encombrement du calendrier (3 colonnes) — les jours de repos disent
--      quand l'équipe a joué pour la dernière fois, pas la charge accumulée.
--      Deux équipes à trois jours de repos ne sont pas comparables si l'une
--      sort de son quatrième match en quinze jours.
--
--   3. Solidité et stérilité (2 colonnes) — les deux moitiés du BTTS,
--      calculées par `features/form.py` depuis toujours et jetées faute de
--      colonne d'accueil.
--
-- SQLite accepte ADD COLUMN sans reconstruire la table. Les lignes existantes
-- gardent NULL.
--
-- ⚠️ APRÈS CETTE MIGRATION, RECALCULER LES FEATURES :
--
--     python -m pipelines.feature_pipeline
--
-- Sans ce recalcul les quinze colonnes resteront nulles : la migration crée
-- les colonnes, elle ne les remplit pas.
--
-- Cette migration n'est PAS idempotente — SQLite refuse ADD COLUMN sur une
-- colonne existante. Une seconde exécution échoue proprement, sans rien
-- modifier. Pour vérifier si elle a déjà été appliquée :
--
--     sqlite3 data/pronostic.db "PRAGMA table_info(features);" | grep ht_draw_rate
--
-- Une ligne renvoyée signifie que la migration est déjà passée.

BEGIN TRANSACTION;

-- 1. Première mi-temps.
ALTER TABLE features ADD COLUMN ht_home_win_rate REAL;
ALTER TABLE features ADD COLUMN ht_away_win_rate REAL;
ALTER TABLE features ADD COLUMN ht_draw_rate REAL;
ALTER TABLE features ADD COLUMN ht_home_goals_avg REAL;
ALTER TABLE features ADD COLUMN ht_away_goals_avg REAL;
ALTER TABLE features ADD COLUMN ht_total_goals_avg REAL;
ALTER TABLE features ADD COLUMN ht_over_05_rate REAL;
ALTER TABLE features ADD COLUMN ht_over_15_rate REAL;
ALTER TABLE features ADD COLUMN ht_over_25_rate REAL;
ALTER TABLE features ADD COLUMN ht_over_35_rate REAL;

-- 2. Encombrement du calendrier.
ALTER TABLE features ADD COLUMN rest_days_diff INTEGER;
ALTER TABLE features ADD COLUMN matches_last_7_days INTEGER;
ALTER TABLE features ADD COLUMN matches_last_14_days INTEGER;

-- 3. Solidité et stérilité.
ALTER TABLE features ADD COLUMN clean_sheets_5 INTEGER;
ALTER TABLE features ADD COLUMN failed_to_score_5 INTEGER;

COMMIT;

-- Vérification (à lancer après le recalcul des features) :
--
--   SELECT COUNT(*)                              AS lignes,
--          COUNT(ht_draw_rate)                   AS avec_mi_temps,
--          COUNT(matches_last_7_days)            AS avec_calendrier,
--          COUNT(failed_to_score_5)              AS avec_sterilite,
--          ROUND(AVG(data_completeness), 3)      AS remplissage_moyen
--   FROM features;
--
-- `avec_mi_temps` restera inférieur à `lignes` : les premières journées de
-- chaque saison n'ont pas assez d'historique pour fonder un taux, et une
-- valeur plausible ne doit jamais y être substituée.
