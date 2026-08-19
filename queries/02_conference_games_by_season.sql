-- All MIAA conference games from a given season.
-- Change the season_year filter to explore other years.
SELECT
    g.game_date,
    ht.team_name AS home_team,
    at.team_name AS away_team,
    g.home_score,
    g.away_score
FROM games AS g
JOIN seasons AS s ON g.season_id = s.season_id
JOIN teams AS ht ON g.home_team_id = ht.team_id
JOIN teams AS at ON g.away_team_id = at.team_id
WHERE s.season_year = 2025
  AND g.is_conference_game = TRUE
ORDER BY g.game_date;
