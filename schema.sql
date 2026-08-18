BEGIN;

-- ============================================================
-- Kalamazoo Football SQL Portfolio
-- PostgreSQL schema
-- ============================================================

-- ------------------------------------------------------------
-- 1. teams
-- One row per football program.
-- ------------------------------------------------------------
CREATE TABLE teams (
    team_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_name VARCHAR(100) NOT NULL UNIQUE,
    short_name VARCHAR(50),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- ------------------------------------------------------------
-- 2. seasons
-- One row per football season represented in the database.
-- The source intentionally excludes the shortened 2020 season.
-- ------------------------------------------------------------
CREATE TABLE seasons (
    season_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season_year SMALLINT NOT NULL UNIQUE,

    CONSTRAINT chk_seasons_reasonable_year
        CHECK (season_year BETWEEN 1900 AND 2100)
);

-- ------------------------------------------------------------
-- 3. conferences
-- One row per athletic conference.
-- ------------------------------------------------------------
CREATE TABLE conferences (
    conference_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conference_name VARCHAR(150) NOT NULL UNIQUE,
    conference_abbreviation VARCHAR(20) NOT NULL UNIQUE
);

-- ------------------------------------------------------------
-- 4. team_conference_memberships
-- Historical conference membership by team and season.
-- Grain: one team x one season x one conference.
-- ------------------------------------------------------------
CREATE TABLE team_conference_memberships (
    team_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    conference_id INTEGER NOT NULL,

    PRIMARY KEY (team_id, season_id, conference_id),

    CONSTRAINT fk_membership_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id),

    CONSTRAINT fk_membership_season
        FOREIGN KEY (season_id)
        REFERENCES seasons(season_id),

    CONSTRAINT fk_membership_conference
        FOREIGN KEY (conference_id)
        REFERENCES conferences(conference_id)
);

-- ------------------------------------------------------------
-- 5. games
-- One row per football game.
-- Scores are stored from the neutral home/away perspective,
-- rather than the Kalamazoo/opp perspective used by the CSV.
-- ------------------------------------------------------------
CREATE TABLE games (
    game_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season_id INTEGER NOT NULL,
    game_date DATE NOT NULL,
    home_team_id INTEGER NOT NULL,
    away_team_id INTEGER NOT NULL,
    home_score SMALLINT NOT NULL,
    away_score SMALLINT NOT NULL,
    is_conference_game BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT fk_games_season
        FOREIGN KEY (season_id)
        REFERENCES seasons(season_id),

    CONSTRAINT fk_games_home_team
        FOREIGN KEY (home_team_id)
        REFERENCES teams(team_id),

    CONSTRAINT fk_games_away_team
        FOREIGN KEY (away_team_id)
        REFERENCES teams(team_id),

    CONSTRAINT chk_games_different_teams
        CHECK (home_team_id <> away_team_id),

    CONSTRAINT chk_games_home_score_nonnegative
        CHECK (home_score >= 0),

    CONSTRAINT chk_games_away_score_nonnegative
        CHECK (away_score >= 0),

    CONSTRAINT uq_games_date_home_away
        UNIQUE (game_date, home_team_id, away_team_id)
);

-- ------------------------------------------------------------
-- 6. team_game_stats
-- Grain: one team x one game.
--
-- Each game normally has two rows: one for each team.
--
-- NULL means the value is not available in the source data.
-- In the initial CSV:
--   * Kalamazoo rushing_attempts is unavailable.
--   * Opponent defensive statistics are unavailable.
-- ------------------------------------------------------------
CREATE TABLE team_game_stats (
    game_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,

    -- Offense
    rushing_attempts SMALLINT,
    rushing_yards INTEGER,
    rushing_touchdowns SMALLINT,
    longest_rush SMALLINT,
    pass_completions SMALLINT,
    passing_yards INTEGER,
    passing_touchdowns SMALLINT,
    longest_pass SMALLINT,

    -- Defense
    solo_tackles SMALLINT,
    assisted_tackles SMALLINT,
    tackles_for_loss SMALLINT,
    tfl_yards SMALLINT,
    sacks SMALLINT,
    sack_yards SMALLINT,
    forced_fumbles SMALLINT,
    fumble_recoveries SMALLINT,
    interceptions SMALLINT,

    PRIMARY KEY (game_id, team_id),

    CONSTRAINT fk_team_game_stats_game
        FOREIGN KEY (game_id)
        REFERENCES games(game_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_team_game_stats_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id),

    CONSTRAINT chk_tgs_rushing_attempts_nonnegative
        CHECK (rushing_attempts IS NULL OR rushing_attempts >= 0),

    CONSTRAINT chk_tgs_rushing_touchdowns_nonnegative
        CHECK (rushing_touchdowns IS NULL OR rushing_touchdowns >= 0),

    CONSTRAINT chk_tgs_longest_rush_nonnegative
        CHECK (longest_rush IS NULL OR longest_rush >= 0),

    CONSTRAINT chk_tgs_pass_completions_nonnegative
        CHECK (pass_completions IS NULL OR pass_completions >= 0),

    CONSTRAINT chk_tgs_passing_touchdowns_nonnegative
        CHECK (passing_touchdowns IS NULL OR passing_touchdowns >= 0),

    CONSTRAINT chk_tgs_longest_pass_nonnegative
        CHECK (longest_pass IS NULL OR longest_pass >= 0),

    CONSTRAINT chk_tgs_solo_tackles_nonnegative
        CHECK (solo_tackles IS NULL OR solo_tackles >= 0),

    CONSTRAINT chk_tgs_assisted_tackles_nonnegative
        CHECK (assisted_tackles IS NULL OR assisted_tackles >= 0),

    CONSTRAINT chk_tgs_tackles_for_loss_nonnegative
        CHECK (tackles_for_loss IS NULL OR tackles_for_loss >= 0),

    CONSTRAINT chk_tgs_tfl_yards_nonnegative
        CHECK (tfl_yards IS NULL OR tfl_yards >= 0),

    CONSTRAINT chk_tgs_sacks_nonnegative
        CHECK (sacks IS NULL OR sacks >= 0),

    CONSTRAINT chk_tgs_sack_yards_nonnegative
        CHECK (sack_yards IS NULL OR sack_yards >= 0),

    CONSTRAINT chk_tgs_forced_fumbles_nonnegative
        CHECK (forced_fumbles IS NULL OR forced_fumbles >= 0),

    CONSTRAINT chk_tgs_fumble_recoveries_nonnegative
        CHECK (fumble_recoveries IS NULL OR fumble_recoveries >= 0),

    CONSTRAINT chk_tgs_interceptions_nonnegative
        CHECK (interceptions IS NULL OR interceptions >= 0)
);

-- Common join/filter paths used by the portfolio queries.
CREATE INDEX idx_games_season_id
    ON games(season_id);

CREATE INDEX idx_games_home_team_id
    ON games(home_team_id);

CREATE INDEX idx_games_away_team_id
    ON games(away_team_id);

CREATE INDEX idx_team_game_stats_team_id
    ON team_game_stats(team_id);

CREATE INDEX idx_memberships_season_conference
    ON team_conference_memberships(season_id, conference_id);

COMMIT;
