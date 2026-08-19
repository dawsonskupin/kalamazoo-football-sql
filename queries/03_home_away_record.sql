-- Kalamazoo's overall home vs. away win/loss record
-- across all 10 seasons in the database.
SELECT
    CASE
        WHEN g.home_team_id = k.team_id THEN 'Home'
        ELSE 'Away'
    END AS location,
    COUNT(*) AS games_played,
    SUM(
        CASE
            WHEN g.home_team_id = k.team_id AND g.home_score > g.away_score THEN 1
            WHEN g.away_team_id = k.team_id AND g.away_score > g.home_score THEN 1
            ELSE 0
        END
    ) AS wins
FROM games AS g
JOIN teams AS k ON k.team_name = 'Kalamazoo'
WHERE g.home_team_id = k.team_id OR g.away_team_id = k.team_id
GROUP BY location;