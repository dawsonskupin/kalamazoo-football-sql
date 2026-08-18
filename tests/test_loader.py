"""Tests for the Kalamazoo football PostgreSQL loader.

Two tests are pure unit tests for the trickiest row-level transformation.
The final test is an integration test that rebuilds a DEDICATED test database,
loads the complete CSV, and verifies the expected table grain.

Environment variables for the integration test:
    TEST_DATABASE_URL
        Required. Must point to a PostgreSQL database whose database name
        contains the word "test". Example:
        postgresql://postgres:postgres@localhost:5432/kalamazoo_football_test

    SOURCE_CSV_PATH
        Optional. Defaults to data/raw/kalamazoo_football.csv in the repo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Make scripts/load_data.py importable when pytest runs from the repo root.
sys.path.insert(0, str(SCRIPTS_DIR))

from load_data import load_data, transform_game  # noqa: E402


SCHEMA_PATH = REPO_ROOT / "schema.sql"
DEFAULT_SOURCE_CSV_PATH = REPO_ROOT / "data" / "raw" / "kalamazoo_football.csv"


# ============================================================
# Unit tests: Home_Away + scores -> neutral home/away fields
# ============================================================


def test_at_austin_maps_to_reversed_home_away_scores() -> None:
    """9/6/2025 at Austin: Austin 10, Kalamazoo 14."""
    row = {
        "Date": "9/6/2025",
        "Home_Away": "at",
        "Opponent": "Austin",
        "Points_for": 14,
        "Points_against": 10,
    }

    result = transform_game(
        row=row,
        kalamazoo_team_id="Kalamazoo",
        opponent_team_id="Austin",
    )

    assert result == {
        "home_team_id": "Austin",
        "away_team_id": "Kalamazoo",
        "home_score": 10,
        "away_score": 14,
    }


def test_vs_bethany_maps_without_score_reversal() -> None:
    """9/13/2025 vs Bethany (WV): Kalamazoo 50, Bethany 7."""
    row = {
        "Date": "09/13/2025",
        "Home_Away": "vs",
        "Opponent": "Bethany (WV)",
        "Points_for": 50,
        "Points_against": 7,
    }

    result = transform_game(
        row=row,
        kalamazoo_team_id="Kalamazoo",
        opponent_team_id="Bethany (WV)",
    )

    assert result == {
        "home_team_id": "Kalamazoo",
        "away_team_id": "Bethany (WV)",
        "home_score": 50,
        "away_score": 7,
    }


# ============================================================
# Integration-test helpers
# ============================================================


def require_test_database_url() -> str:
    """Return TEST_DATABASE_URL or skip the integration test."""
    database_url = os.getenv("TEST_DATABASE_URL")

    if not database_url:
        pytest.skip(
            "TEST_DATABASE_URL is not set. "
            "Use a dedicated PostgreSQL test database to run this test."
        )

    return database_url


def get_source_csv_path() -> Path:
    """Return SOURCE_CSV_PATH or the repository default."""
    configured = os.getenv("SOURCE_CSV_PATH")
    data_path = Path(configured) if configured else DEFAULT_SOURCE_CSV_PATH

    if not data_path.exists():
        pytest.skip(
            f"Source CSV not found at {data_path}. Set SOURCE_CSV_PATH or "
            "place the file at data/raw/kalamazoo_football.csv."
        )

    return data_path


def assert_safe_test_database(conn: psycopg.Connection) -> None:
    """Refuse destructive setup unless the database clearly looks like a test DB."""
    database_name = conn.info.dbname or ""

    if "test" not in database_name.lower():
        pytest.fail(
            "Integration test refused to reset the database because its name "
            f"does not contain 'test': {database_name!r}. Point "
            "TEST_DATABASE_URL at a dedicated test database."
        )


def reset_tables(conn: psycopg.Connection) -> None:
    """Drop only this project's six tables, in dependency-safe order."""
    conn.execute("DROP TABLE IF EXISTS team_game_stats CASCADE;")
    conn.execute("DROP TABLE IF EXISTS games CASCADE;")
    conn.execute("DROP TABLE IF EXISTS team_conference_memberships CASCADE;")
    conn.execute("DROP TABLE IF EXISTS conferences CASCADE;")
    conn.execute("DROP TABLE IF EXISTS seasons CASCADE;")
    conn.execute("DROP TABLE IF EXISTS teams CASCADE;")


def apply_schema(conn: psycopg.Connection) -> None:
    """Execute schema.sql one statement at a time."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # schema.sql contains ordinary DDL only, so splitting on semicolons is
    # sufficient here. If procedural SQL is added later, replace this helper
    # with a migration tool or psql invocation.
    statements = [
        statement.strip()
        for statement in schema_sql.split(";")
        if statement.strip()
    ]

    for statement in statements:
        conn.execute(statement)


# ============================================================
# Integration test: complete 100-game load
# ============================================================


def test_full_load_creates_100_games_and_200_team_game_rows() -> None:
    """A full load preserves the intended one-game / two-team-row grain."""
    database_url = require_test_database_url()
    data_path = get_source_csv_path()

    # Set up the dedicated test database from scratch.
    # autocommit=True is intentional because schema.sql contains its own
    # BEGIN / COMMIT statements.
    with psycopg.connect(database_url, autocommit=True) as conn:
        assert_safe_test_database(conn)
        reset_tables(conn)
        apply_schema(conn)

    # Run the same loader that will be used by the real project database.
    load_data(
        data_path=data_path,
        database_url=database_url,
    )

    # Query PostgreSQL directly after the full load rather than relying only
    # on counts returned by the Python function.
    with psycopg.connect(database_url) as conn:
        games_count = conn.execute(
            "SELECT COUNT(*) FROM games;"
        ).fetchone()[0]

        team_game_stats_count = conn.execute(
            "SELECT COUNT(*) FROM team_game_stats;"
        ).fetchone()[0]

        assert games_count == 100
        assert team_game_stats_count == 200

        # Bonus grain check: every loaded game must have exactly two
        # team_game_stats rows, one for each participating team.
        invalid_game_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT game_id
                FROM team_game_stats
                GROUP BY game_id
                HAVING COUNT(*) <> 2
            ) AS invalid_games;
            """
        ).fetchone()[0]

        assert invalid_game_count == 0
