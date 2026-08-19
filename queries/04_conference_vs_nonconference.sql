-- Kalamazoo's win/loss record split by conference vs.
-- non-conference games, across all 10 seasons.
SELECT
    CASE
        WHEN g.is_conference_game THEN 'Conference'
        ELSE 'Non-Conference'
    END AS game_type,
    COUNT(*) AS games_played,
    SUM(
        CASE
            WHEN g.home_team_id = k.team_id AND g.home_score > g.away_score THEN 1
            WHEN g.away_team_id = k.team_id AND g.away_score > g.home_score THEN 1
            ELSE 0
        END
    ) AS wins,
    SUM(
        CASE
            WHEN g.home_team_id = k.team_id AND g.home_score < g.away_score THEN 1
            WHEN g.away_team_id = k.team_id AND g.away_score < g.home_score THEN 1
            ELSE 0
        END
    ) AS losses
FROM games AS g
JOIN teams AS k ON k.team_name = 'Kalamazoo'
WHERE g.home_team_id = k.team_id OR g.away_team_id = k.team_id
GROUP BY game_type;