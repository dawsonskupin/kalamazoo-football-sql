"""Load the Kalamazoo football CSV into the normalized PostgreSQL schema.

The source CSV is Kalamazoo-centric: each row represents a Kalamazoo game,
Points_for / Points_against are from Kalamazoo's perspective, Off_* columns
belong to Kalamazoo, and Opp_* columns belong to the opponent.

The database is team-neutral. One source row becomes:
    * one row in games
    * one Kalamazoo row in team_game_stats
    * one opponent row in team_game_stats
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg import Connection


# ============================================================
# Paths / connection defaults
# ============================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "raw" / "kalamazoo_football.csv"

DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/kalamazoo_football",
)


# ============================================================
# Source / domain constants
# ============================================================

KALAMAZOO = "Kalamazoo"
MIAA_NAME = "Michigan Intercollegiate Athletic Association"
MIAA_ABBREVIATION = "MIAA"

SOURCE_SEASONS = (
    2015,
    2016,
    2017,
    2018,
    2019,
    2021,
    2022,
    2023,
    2024,
    2025,
)

# Football-playing MIAA members relevant to this dataset before Calvin's
# football program began MIAA play in 2024. Saint Mary's is not included
# because it does not sponsor football.
BASE_MIAA_FOOTBALL_TEAMS = {
    "Adrian",
    "Albion",
    "Alma",
    "Hope",
    "Kalamazoo",
    "Olivet",
    "Trine",
}

MIAA_TEAMS_BY_SEASON = {
    year: set(BASE_MIAA_FOOTBALL_TEAMS)
    for year in SOURCE_SEASONS
}
MIAA_TEAMS_BY_SEASON[2024].add("Calvin")
MIAA_TEAMS_BY_SEASON[2025].add("Calvin")

# Keep scraped names as-is for the initial load, apart from surrounding
# whitespace. If a future scrape exposes confirmed aliases, add explicit
# mappings here rather than silently guessing.
TEAM_NAME_ALIASES: dict[str, str] = {}

REQUIRED_COLUMNS = {
    "Date",
    "Home_Away",
    "Opponent",
    "Points_for",
    "Points_against",
    "Record",
    "Conf_Record",
    "Off_Rush_YDS",
    "Off_Rush_TD",
    "Off_Rush_Long",
    "Off_Rec_ATT",
    "Off_Rec_YDS",
    "Off_Rec_TD",
    "Off_Rec_Long",
    "Off_Pass_YDS",
    "Off_Pass_TD",
    "Off_Pass_Long",
    "Solo",
    "Ast",
    "Tot",
    "TFL",
    "TFL_YDS",
    "Sacks",
    "Sack_YDS",
    "FF",
    "FR",
    "INT",
    "Opp_Rush_ATT",
    "Opp_Rush_YDS",
    "Opp_Rush_TD",
    "Opp_Rush_Long",
    "Opp_Rec_ATT",
    "Opp_Rec_YDS",
    "Opp_Rec_TD",
    "Opp_Rec_Long",
    "Opp_Pass_YDS",
    "Opp_Pass_TD",
    "Opp_Pass_Long",
}

DUPLICATE_COLUMN_PAIRS = (
    ("Off_Rec_YDS", "Off_Pass_YDS"),
    ("Off_Rec_TD", "Off_Pass_TD"),
    ("Off_Rec_Long", "Off_Pass_Long"),
    ("Opp_Rec_YDS", "Opp_Pass_YDS"),
    ("Opp_Rec_TD", "Opp_Pass_TD"),
    ("Opp_Rec_Long", "Opp_Pass_Long"),
)


# ============================================================
# General helpers
# ============================================================


def normalize_team_name(name: Any) -> str:
    """Return the canonical name used by the database."""
    cleaned = str(name).strip()
    return TEAM_NAME_ALIASES.get(cleaned, cleaned)


def int_or_none(value: Any) -> int | None:
    """Convert a source value to int while preserving unavailable values."""
    if pd.isna(value):
        return None
    return int(value)


def read_source_csv(data_path: Path) -> pd.DataFrame:
    """Read, validate, and minimally clean the source CSV."""
    df = pd.read_csv(data_path)
    validate_source_data(df)

    # Source dates are month/day/year strings such as 9/6/2025 and 09/13/2025.
    df["Date"] = pd.to_datetime(df["Date"], errors="raise").dt.date
    df["Opponent"] = df["Opponent"].map(normalize_team_name)
    df["season_year"] = pd.to_datetime(df["Date"]).dt.year.astype(int)

    source_years = set(df["season_year"].unique())
    expected_years = set(SOURCE_SEASONS)

    if source_years != expected_years:
        raise ValueError(
            "Source seasons do not match the expected dataset. "
            f"Found {sorted(source_years)}; expected {sorted(expected_years)}."
        )

    return df


def validate_source_data(df: pd.DataFrame) -> None:
    """Fail early if source assumptions used by the ETL no longer hold."""
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(
            "Source CSV is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    locations = set(df["Home_Away"].astype(str).str.strip().str.lower())
    unexpected_locations = locations - {"at", "vs"}
    if unexpected_locations:
        raise ValueError(
            "Unexpected Home_Away values: "
            + ", ".join(sorted(unexpected_locations))
        )

    # These fields were verified as duplicates in the original 100-row CSV.
    # Re-check on every load so a later scrape cannot silently violate the
    # assumption that only the Pass_* version needs to be stored.
    for left, right in DUPLICATE_COLUMN_PAIRS:
        unequal = ~df[left].eq(df[right])
        if unequal.any():
            rows = df.index[unequal].tolist()[:10]
            raise ValueError(
                f"Expected duplicate columns {left} and {right} to match, "
                f"but they differ at source row indexes {rows}."
            )

    # Tot is intentionally not stored because it is derived from Solo + Ast.
    bad_totals = ~df["Tot"].eq(df["Solo"] + df["Ast"])
    if bad_totals.any():
        rows = df.index[bad_totals].tolist()[:10]
        raise ValueError(
            "Expected Tot = Solo + Ast, but the relationship fails at "
            f"source row indexes {rows}."
        )


# ============================================================
# Reference-table upserts
# ============================================================


def get_or_create_team(conn: Connection, team_name: str) -> int:
    row = conn.execute(
        """
        INSERT INTO teams (team_name)
        VALUES (%s)
        ON CONFLICT (team_name)
        DO UPDATE SET team_name = EXCLUDED.team_name
        RETURNING team_id;
        """,
        (team_name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(f"Could not get team_id for {team_name!r}.")

    return row[0]


def get_or_create_season(conn: Connection, season_year: int) -> int:
    row = conn.execute(
        """
        INSERT INTO seasons (season_year)
        VALUES (%s)
        ON CONFLICT (season_year)
        DO UPDATE SET season_year = EXCLUDED.season_year
        RETURNING season_id;
        """,
        (season_year,),
    ).fetchone()

    if row is None:
        raise RuntimeError(f"Could not get season_id for {season_year}.")

    return row[0]


def get_or_create_conference(conn: Connection) -> int:
    row = conn.execute(
        """
        INSERT INTO conferences (
            conference_name,
            conference_abbreviation
        )
        VALUES (%s, %s)
        ON CONFLICT (conference_abbreviation)
        DO UPDATE SET conference_name = EXCLUDED.conference_name
        RETURNING conference_id;
        """,
        (MIAA_NAME, MIAA_ABBREVIATION),
    ).fetchone()

    if row is None:
        raise RuntimeError("Could not get conference_id for the MIAA.")

    return row[0]


def load_reference_data(
    conn: Connection,
    df: pd.DataFrame,
) -> tuple[dict[str, int], dict[int, int], int]:
    """Load teams, seasons, conference, and historical memberships."""
    season_ids = {
        year: get_or_create_season(conn, year)
        for year in SOURCE_SEASONS
    }

    team_names = set(df["Opponent"].unique())
    team_names.add(KALAMAZOO)

    # Add known MIAA football members even if a member does not appear as an
    # opponent in one of the scraped seasons.
    for member_names in MIAA_TEAMS_BY_SEASON.values():
        team_names.update(member_names)

    team_ids = {
        team_name: get_or_create_team(conn, team_name)
        for team_name in sorted(team_names)
    }

    conference_id = get_or_create_conference(conn)

    load_conference_memberships(
        conn=conn,
        team_ids=team_ids,
        season_ids=season_ids,
        conference_id=conference_id,
    )

    return team_ids, season_ids, conference_id


def load_conference_memberships(
    conn: Connection,
    team_ids: dict[str, int],
    season_ids: dict[int, int],
    conference_id: int,
) -> None:
    """Insert MIAA football membership rows by season."""
    for season_year, member_names in MIAA_TEAMS_BY_SEASON.items():
        season_id = season_ids[season_year]

        for team_name in sorted(member_names):
            conn.execute(
                """
                INSERT INTO team_conference_memberships (
                    team_id,
                    season_id,
                    conference_id
                )
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (
                    team_ids[team_name],
                    season_id,
                    conference_id,
                ),
            )


# ============================================================
# Conference-game rule
# ============================================================


def is_miaa_conference_game(
    team_a: str,
    team_b: str,
    season_year: int,
) -> bool:
    """Return True when both teams are MIAA football members that season."""
    members = MIAA_TEAMS_BY_SEASON.get(season_year, set())
    return team_a in members and team_b in members


# ============================================================
# Home / away score transformation
# ============================================================


def transform_game(
    row: Any,
    kalamazoo_team_id: Any,
    opponent_team_id: Any,
) -> dict[str, Any]:
    """Convert a Kalamazoo-centric source row to neutral game fields.

    Source rules:
        Home_Away == "vs"
            Kalamazoo is the home team.
            Points_for belongs to the home team.
            Points_against belongs to the away team.

        Home_Away == "at"
            Kalamazoo is the away team.
            Points_against belongs to the home opponent.
            Points_for belongs to the away Kalamazoo team.

    The IDs are typed as Any on purpose so this pure transformation can be
    unit-tested with readable strings such as "Austin" and "Kalamazoo".
    Production code passes integer team IDs.
    """
    location = str(row["Home_Away"]).strip().lower()
    kalamazoo_score = int(row["Points_for"])
    opponent_score = int(row["Points_against"])

    if location == "vs":
        return {
            "home_team_id": kalamazoo_team_id,
            "away_team_id": opponent_team_id,
            "home_score": kalamazoo_score,
            "away_score": opponent_score,
        }

    if location == "at":
        return {
            "home_team_id": opponent_team_id,
            "away_team_id": kalamazoo_team_id,
            "home_score": opponent_score,
            "away_score": kalamazoo_score,
        }

    raise ValueError(
        f"Unexpected Home_Away value {row['Home_Away']!r}; expected 'at' or 'vs'."
    )


# ============================================================
# Fact-table upserts
# ============================================================


def insert_game(
    conn: Connection,
    row: Any,
    season_id: int,
    season_year: int,
    kalamazoo_team_id: int,
    opponent_team_id: int,
    opponent_name: str,
) -> int:
    """Transform and upsert one source game, then return game_id."""
    game = transform_game(
        row=row,
        kalamazoo_team_id=kalamazoo_team_id,
        opponent_team_id=opponent_team_id,
    )

    conference_game = is_miaa_conference_game(
        KALAMAZOO,
        opponent_name,
        season_year,
    )

    result = conn.execute(
        """
        INSERT INTO games (
            season_id,
            game_date,
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            is_conference_game
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_date, home_team_id, away_team_id)
        DO UPDATE SET
            season_id = EXCLUDED.season_id,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            is_conference_game = EXCLUDED.is_conference_game
        RETURNING game_id;
        """,
        (
            season_id,
            row["Date"],
            game["home_team_id"],
            game["away_team_id"],
            game["home_score"],
            game["away_score"],
            conference_game,
        ),
    ).fetchone()

    if result is None:
        raise RuntimeError("Could not insert or retrieve game_id.")

    return result[0]


def build_kalamazoo_stats(row: Any) -> dict[str, int | None]:
    """Map Kalamazoo source columns to the neutral stats schema."""
    return {
        # Not available for Kalamazoo in the current source CSV.
        "rushing_attempts": None,
        "rushing_yards": int_or_none(row["Off_Rush_YDS"]),
        "rushing_touchdowns": int_or_none(row["Off_Rush_TD"]),
        "longest_rush": int_or_none(row["Off_Rush_Long"]),

        # Off_Rec_ATT is retained but renamed to pass_completions.
        # Duplicate Off_Rec_YDS / TD / Long values are intentionally ignored.
        "pass_completions": int_or_none(row["Off_Rec_ATT"]),
        "passing_yards": int_or_none(row["Off_Pass_YDS"]),
        "passing_touchdowns": int_or_none(row["Off_Pass_TD"]),
        "longest_pass": int_or_none(row["Off_Pass_Long"]),

        # Kalamazoo defensive fields are present in the source.
        # Tot is intentionally not stored because Tot = Solo + Ast.
        "solo_tackles": int_or_none(row["Solo"]),
        "assisted_tackles": int_or_none(row["Ast"]),
        "tackles_for_loss": int_or_none(row["TFL"]),
        "tfl_yards": int_or_none(row["TFL_YDS"]),
        "sacks": int_or_none(row["Sacks"]),
        "sack_yards": int_or_none(row["Sack_YDS"]),
        "forced_fumbles": int_or_none(row["FF"]),
        "fumble_recoveries": int_or_none(row["FR"]),
        "interceptions": int_or_none(row["INT"]),
    }


def build_opponent_stats(row: Any) -> dict[str, int | None]:
    """Map opponent source columns to the neutral stats schema."""
    return {
        "rushing_attempts": int_or_none(row["Opp_Rush_ATT"]),
        "rushing_yards": int_or_none(row["Opp_Rush_YDS"]),
        "rushing_touchdowns": int_or_none(row["Opp_Rush_TD"]),
        "longest_rush": int_or_none(row["Opp_Rush_Long"]),

        # Opp_Rec_ATT is retained but renamed to pass_completions.
        # Duplicate Opp_Rec_YDS / TD / Long values are intentionally ignored.
        "pass_completions": int_or_none(row["Opp_Rec_ATT"]),
        "passing_yards": int_or_none(row["Opp_Pass_YDS"]),
        "passing_touchdowns": int_or_none(row["Opp_Pass_TD"]),
        "longest_pass": int_or_none(row["Opp_Pass_Long"]),

        # Opponent defensive statistics are not available in the source CSV.
        "solo_tackles": None,
        "assisted_tackles": None,
        "tackles_for_loss": None,
        "tfl_yards": None,
        "sacks": None,
        "sack_yards": None,
        "forced_fumbles": None,
        "fumble_recoveries": None,
        "interceptions": None,
    }


def upsert_team_game_stats(
    conn: Connection,
    game_id: int,
    team_id: int,
    stats: dict[str, int | None],
) -> None:
    """Insert or update one team x game statistics row."""
    conn.execute(
        """
        INSERT INTO team_game_stats (
            game_id,
            team_id,
            rushing_attempts,
            rushing_yards,
            rushing_touchdowns,
            longest_rush,
            pass_completions,
            passing_yards,
            passing_touchdowns,
            longest_pass,
            solo_tackles,
            assisted_tackles,
            tackles_for_loss,
            tfl_yards,
            sacks,
            sack_yards,
            forced_fumbles,
            fumble_recoveries,
            interceptions
        )
        VALUES (
            %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (game_id, team_id)
        DO UPDATE SET
            rushing_attempts = EXCLUDED.rushing_attempts,
            rushing_yards = EXCLUDED.rushing_yards,
            rushing_touchdowns = EXCLUDED.rushing_touchdowns,
            longest_rush = EXCLUDED.longest_rush,
            pass_completions = EXCLUDED.pass_completions,
            passing_yards = EXCLUDED.passing_yards,
            passing_touchdowns = EXCLUDED.passing_touchdowns,
            longest_pass = EXCLUDED.longest_pass,
            solo_tackles = EXCLUDED.solo_tackles,
            assisted_tackles = EXCLUDED.assisted_tackles,
            tackles_for_loss = EXCLUDED.tackles_for_loss,
            tfl_yards = EXCLUDED.tfl_yards,
            sacks = EXCLUDED.sacks,
            sack_yards = EXCLUDED.sack_yards,
            forced_fumbles = EXCLUDED.forced_fumbles,
            fumble_recoveries = EXCLUDED.fumble_recoveries,
            interceptions = EXCLUDED.interceptions;
        """,
        (
            game_id,
            team_id,
            stats["rushing_attempts"],
            stats["rushing_yards"],
            stats["rushing_touchdowns"],
            stats["longest_rush"],
            stats["pass_completions"],
            stats["passing_yards"],
            stats["passing_touchdowns"],
            stats["longest_pass"],
            stats["solo_tackles"],
            stats["assisted_tackles"],
            stats["tackles_for_loss"],
            stats["tfl_yards"],
            stats["sacks"],
            stats["sack_yards"],
            stats["forced_fumbles"],
            stats["fumble_recoveries"],
            stats["interceptions"],
        ),
    )


def insert_kalamazoo_stats(
    conn: Connection,
    game_id: int,
    kalamazoo_team_id: int,
    row: Any,
) -> None:
    """Insert Kalamazoo's team_game_stats row for one game."""
    upsert_team_game_stats(
        conn=conn,
        game_id=game_id,
        team_id=kalamazoo_team_id,
        stats=build_kalamazoo_stats(row),
    )


def insert_opponent_stats(
    conn: Connection,
    game_id: int,
    opponent_team_id: int,
    row: Any,
) -> None:
    """Insert the opponent's team_game_stats row for one game."""
    upsert_team_game_stats(
        conn=conn,
        game_id=game_id,
        team_id=opponent_team_id,
        stats=build_opponent_stats(row),
    )


# ============================================================
# Full load
# ============================================================


def load_data(
    data_path: Path | str = DEFAULT_DATA_PATH,
    database_url: str = DEFAULT_DATABASE_URL,
) -> tuple[int, int]:
    """Load the full CSV and return current games/stat-row counts."""
    data_path = Path(data_path)

    if not data_path.exists():
        raise FileNotFoundError(
            f"Source CSV not found at {data_path}. "
            "Pass --data or place it at data/raw/kalamazoo_football.csv."
        )

    df = read_source_csv(data_path)

    # psycopg's connection context commits the transaction if the block exits
    # successfully and rolls it back if an exception is raised.
    with psycopg.connect(database_url) as conn:
        team_ids, season_ids, _conference_id = load_reference_data(conn, df)
        kalamazoo_team_id = team_ids[KALAMAZOO]

        for _, row in df.iterrows():
            season_year = int(row["season_year"])
            season_id = season_ids[season_year]
            opponent_name = row["Opponent"]
            opponent_team_id = team_ids[opponent_name]

            # One source row -> one neutral games row.
            # transform_game() inside insert_game() performs the key
            # Home_Away / Points_for / Points_against transformation.
            game_id = insert_game(
                conn=conn,
                row=row,
                season_id=season_id,
                season_year=season_year,
                kalamazoo_team_id=kalamazoo_team_id,
                opponent_team_id=opponent_team_id,
                opponent_name=opponent_name,
            )

            # One source row -> two team_game_stats rows.
            insert_kalamazoo_stats(
                conn=conn,
                game_id=game_id,
                kalamazoo_team_id=kalamazoo_team_id,
                row=row,
            )

            insert_opponent_stats(
                conn=conn,
                game_id=game_id,
                opponent_team_id=opponent_team_id,
                row=row,
            )

        game_count = conn.execute(
            "SELECT COUNT(*) FROM games;"
        ).fetchone()[0]

        stats_count = conn.execute(
            "SELECT COUNT(*) FROM team_game_stats;"
        ).fetchone()[0]

    return game_count, stats_count


# ============================================================
# Command-line entry point
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load Kalamazoo football CSV data into PostgreSQL."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help=(
            "Path to source CSV. Default: "
            "data/raw/kalamazoo_football.csv"
        ),
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help=(
            "PostgreSQL connection URL. Defaults to DATABASE_URL, then "
            "postgresql://postgres:postgres@localhost:5432/kalamazoo_football"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    game_count, stats_count = load_data(
        data_path=args.data,
        database_url=args.database_url,
    )

    print(f"Load complete: {game_count} games, {stats_count} team-game stat rows.")


if __name__ == "__main__":
    main()
