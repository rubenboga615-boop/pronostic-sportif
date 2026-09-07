-- Migration réversible : ajout de cinq index non uniques (2026-08-22)
--
-- Appliquée à data/pronostic.db. Sauvegarde préalable :
--   backups/pronostic_avant_indexes.db  (integrity_check: ok)
--
-- Sens aller (UP) — idempotent.
-- Sens retour (DOWN) : exécuter les DROP INDEX IF EXISTS correspondants,
-- listés en commentaire à droite de chaque CREATE.

-- 1) Déduplication des matchs (aligné sur _find_existing_match)
BEGIN TRANSACTION;

CREATE INDEX IF NOT EXISTS idx_matches_dedup
    ON matches (provider, match_date, home_team_id, away_team_id);
-- DOWN: DROP INDEX IF EXISTS idx_matches_dedup;

-- 2) Upsert des équipes
CREATE INDEX IF NOT EXISTS idx_teams_lookup
    ON teams (provider, canonical_name);
-- DOWN: DROP INDEX IF EXISTS idx_teams_lookup;

-- 3) Upsert des saisons
CREATE INDEX IF NOT EXISTS idx_seasons_lookup
    ON seasons (competition_id, season_name);
-- DOWN: DROP INDEX IF EXISTS idx_seasons_lookup;

-- 4) Jointures cotes -> matchs
CREATE INDEX IF NOT EXISTS idx_odds_match_id
    ON odds_snapshots (match_id);
-- DOWN: DROP INDEX IF EXISTS idx_odds_match_id;

-- 5) Jointures stats -> match/équipe
CREATE INDEX IF NOT EXISTS idx_tms_match_team
    ON team_match_stats (match_id, team_id);

COMMIT;
-- DOWN: DROP INDEX IF EXISTS idx_tms_match_team;
