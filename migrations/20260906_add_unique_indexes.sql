-- Migration : contraintes d'unicité et index manquants (2026-09-06)
--
-- ⚠️ SAUVEGARDE OBLIGATOIRE AVANT EXÉCUTION.
--     cp data/pronostic.db data/backups/pronostic_avant_unicite.db
--     sqlite3 data/backups/pronostic_avant_unicite.db "PRAGMA integrity_check;"
--
-- Contexte
-- --------
-- L'idempotence des pipelines reposait uniquement sur des SELECT applicatifs
-- avant écriture : rien, au niveau de la base, n'empêchait un doublon en cas
-- d'exécution concurrente ou d'écriture par un script tiers.
--
-- Ces index sont désormais déclarés dans les modèles ORM (`app/models.py`),
-- donc une base créée par `Base.metadata.create_all` les possède d'emblée.
-- Cette migration met à niveau une base existante.
--
-- Vérification préalable — ces trois requêtes doivent toutes retourner 0.
-- Si l'une retourne autre chose, dédoublonner AVANT de créer l'index :
--
--   SELECT COUNT(*) FROM (SELECT match_id, team_id FROM features
--                          GROUP BY 1,2 HAVING COUNT(*) > 1);
--   SELECT COUNT(*) FROM (SELECT match_id, model_version, market, selection
--                           FROM predictions GROUP BY 1,2,3,4 HAVING COUNT(*) > 1);
--   SELECT COUNT(*) FROM (SELECT provider, provider_match_id FROM matches
--                          WHERE provider_match_id IS NOT NULL
--                          GROUP BY 1,2 HAVING COUNT(*) > 1);
--
-- Sens aller (UP) — idempotent.

-- 1) Une seule ligne de features par match et par équipe.
BEGIN TRANSACTION;

CREATE UNIQUE INDEX IF NOT EXISTS uq_features_match_team
    ON features (match_id, team_id);
-- DOWN: DROP INDEX IF EXISTS uq_features_match_team;

-- 2) Clé logique de la prédiction.
CREATE UNIQUE INDEX IF NOT EXISTS uq_predictions_logique
    ON predictions (match_id, model_version, market, selection);
-- DOWN: DROP INDEX IF EXISTS uq_predictions_logique;

-- 3) Un identifiant fournisseur désigne un match et un seul.
CREATE UNIQUE INDEX IF NOT EXISTS uq_matches_provider_match
    ON matches (provider, provider_match_id);
-- DOWN: DROP INDEX IF EXISTS uq_matches_provider_match;

-- 4) Un résultat réglé par match, marché et sélection.
CREATE UNIQUE INDEX IF NOT EXISTS uq_actual_results_logique
    ON actual_results (match_id, market, selection);
-- DOWN: DROP INDEX IF EXISTS uq_actual_results_logique;

-- 5) Sélection des matchs d'une compétition sur une période (classement,
--    moyenne de buts de ligue, backtest par saison).
CREATE INDEX IF NOT EXISTS idx_matches_competition_date
    ON matches (competition_id, match_date);
-- DOWN: DROP INDEX IF EXISTS idx_matches_competition_date;

-- 6) Consultation des prédictions d'un match (API, tableau de bord).
CREATE INDEX IF NOT EXISTS idx_predictions_match
    ON predictions (match_id);

COMMIT;
-- DOWN: DROP INDEX IF EXISTS idx_predictions_match;
