# SQL Concepts Used in This Project

Notes explaining the SQL concepts and functions used in each query,
written while learning SQL for the first time through this project,
to look back on and help me learn.

## JOIN

Combines rows from two tables based on a matching column. Every query
so far uses `JOIN` (specifically an INNER JOIN, the default type) to
pull in related data. For example, `games` only stores `team_id`
numbers, not team names, so we JOIN to `teams` to get the actual name.

```sql
FROM games AS g
JOIN teams AS ht ON g.home_team_id = ht.team_id
```

This says: "for every row in `games`, find the matching row in `teams`
where the id columns line up, and let me refer to that matched team
as `ht`." Doing this twice in the same query (once as `ht`, once as
`at`) is how we get both the home and away team names on one row.

## Table aliases (AS)

Short nicknames for tables so the query is easier to read and write.
`teams AS ht` means "call this instance of the teams table `ht` for
the rest of this query." Necessary here because we join `teams` twice
in the same query, once for the home team, once for the away team,
so we need two different names to tell them apart.

## Scalar subqueries

A query nested inside another query that returns a single value, used
in place of a literal. Instead of hardcoding Kalamazoo's team_id
number (which could differ between the real and test databases), we
look it up dynamically:

```sql
(SELECT team_id FROM teams WHERE team_name = 'Kalamazoo')
```

This runs first, returns one number, and that number gets substituted
into the surrounding query as if we'd typed it directly.

## CASE expressions

SQL's if/then/else. Evaluates conditions in order and returns the
first matching result. Used to translate raw home/away/score data
into something more meaningful, like labeling whether Kalamazoo won:

```sql
CASE
    WHEN g.home_team_id = k.team_id AND g.home_score > g.away_score THEN 1
    WHEN g.away_team_id = k.team_id AND g.away_score > g.home_score THEN 1
    ELSE 0
END
```

## Aggregate functions: COUNT() and SUM()

Functions that collapse many rows into a single summary value.
`COUNT(*)` counts rows; `SUM()` adds up a column (or, as used here,
adds up a column of 1s and 0s produced by a CASE expression. A common
trick for counting how many rows meet a condition).

## GROUP BY

Splits the result set into buckets based on a column's value, then
runs any aggregate functions (COUNT, SUM) separately within each
bucket instead of over the whole table at once.

```sql
GROUP BY s.season_year
```

Without this, `SUM(wins)` would give one number for the entire
database. With it, you get one row per season, each with its own win
total — this is the difference between "how many games did Kalamazoo
win, ever" and "how many games did Kalamazoo win, per year."

## ORDER BY

Sorts the final result rows. Doesn't affect what data comes back,
only the order it's displayed in.

---

*More sections will be added as new concepts are introduced,
window functions and CTEs are coming up next.*