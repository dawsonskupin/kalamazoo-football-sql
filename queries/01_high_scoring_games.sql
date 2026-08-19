-- All games where Kalamazoo scored 30 or more points,
-- with home and away teams shown explicitly.
SELECT
    s.season_year,
    g.game_date,
    ht.team_name AS home_team,
    at.team_name AS away_team,
    g.home_score,
    g.away_score
FROM games AS g
JOIN seasons AS s ON g.season_id = s.season_id
JOIN teams AS ht ON g.home_team_id = ht.team_id
JOIN teams AS at ON g.away_team_id = at.team_id
WHERE
    (g.home_team_id = (SELECT team_id FROM teams WHERE team_name = 'Kalamazoo') AND g.home_score >= 30)
    OR
    (g.away_team_id = (SELECT team_id FROM teams WHERE team_name = 'Kalamazoo') AND g.away_score >= 30)
ORDER BY s.season_year, g.game_date;