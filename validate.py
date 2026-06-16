#!/usr/bin/env python3
"""
Referential integrity validation for the World Cup Parquet set.

Checks (all over data/parquet/*.parquet produced by ingest.py):
  1. Every expected table exists and is non-empty (row counts).
  2. Foreign-key coverage: event/bridge rows reference IDs that exist in the
     corresponding lookup table (goals→matches, goals→teams, goals→players,
     team_appearances→teams/tournaments, matches→tournaments/stadiums, …).
  3. No NULL primary IDs in the core tables.

Usage:
    python3 validate.py [--data-dir ./data/parquet]

Exits 0 if all checks pass, 1 if any fail.
"""

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PASS = "✓"
FAIL = "✗"

# All 27 core tables we expect ingest.py to have produced.
EXPECTED_TABLES = [
    "tournaments", "teams", "players", "stadiums", "managers", "referees",
    "confederations", "matches", "goals", "bookings", "substitutions",
    "penalty_kicks", "team_appearances", "player_appearances",
    "manager_appearances", "referee_appearances", "manager_appointments",
    "referee_appointments", "qualified_teams", "squads", "groups",
    "group_standings", "tournament_standings", "tournament_stages",
    "host_countries", "awards", "award_winners",
]

# (label, child_table, child_col, parent_table, parent_col)
# Only FK pairs where the child column is never expected to be NULL.
FK_CHECKS = [
    ("goals.match_id → matches",             "goals", "match_id", "matches", "match_id"),
    ("goals.team_id → teams",                "goals", "team_id", "teams", "team_id"),
    ("goals.player_id → players",            "goals", "player_id", "players", "player_id"),
    ("matches.tournament_id → tournaments",  "matches", "tournament_id", "tournaments", "tournament_id"),
    ("matches.stadium_id → stadiums",        "matches", "stadium_id", "stadiums", "stadium_id"),
    ("team_appearances.team_id → teams",     "team_appearances", "team_id", "teams", "team_id"),
    ("team_appearances.match_id → matches",  "team_appearances", "match_id", "matches", "match_id"),
    ("bookings.match_id → matches",          "bookings", "match_id", "matches", "match_id"),
    ("squads.player_id → players",           "squads", "player_id", "players", "player_id"),
    ("group_standings.team_id → teams",      "group_standings", "team_id", "teams", "team_id"),
]

# (table, primary id column) that should never be NULL.
NOT_NULL_IDS = [
    ("tournaments", "tournament_id"),
    ("matches", "match_id"),
    ("teams", "team_id"),
    ("players", "player_id"),
    ("goals", "goal_id"),
]


def check(con, label: str, sql: str, expect_zero: bool = True) -> bool:
    val = con.execute(sql).fetchone()[0]
    if expect_zero:
        ok = val == 0
        status = PASS if ok else FAIL
    else:
        ok = True
        status = PASS
    log.info("%s  %s  →  %s", status, label, f"{val:,}" if isinstance(val, int) else val)
    return ok


def main():
    parser = argparse.ArgumentParser(description="Validate World Cup Parquet referential integrity")
    parser.add_argument("--data-dir", default="./data/parquet",
                        help="Directory containing Parquet files (default: ./data/parquet)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    def p(table: str) -> str:
        return str(data_dir / f"{table}.parquet")

    missing = [t for t in EXPECTED_TABLES if not (data_dir / f"{t}.parquet").exists()]
    if missing:
        log.error("Missing Parquet files: %s — run ingest.py first", missing)
        sys.exit(1)

    con = duckdb.connect()
    results = []

    log.info("=" * 60)
    log.info("Row counts")
    log.info("=" * 60)
    for t in EXPECTED_TABLES:
        results.append(check(con, f"{t} row count", f"SELECT count(*) FROM '{p(t)}'", expect_zero=False))
        # A zero-row core table is a failure.
        n = con.execute(f"SELECT count(*) FROM '{p(t)}'").fetchone()[0]
        if n == 0:
            results.append(False)

    log.info("=" * 60)
    log.info("Referential integrity (FK coverage)")
    log.info("=" * 60)
    for label, child, ccol, parent, pcol in FK_CHECKS:
        results.append(check(con, f"orphan {label}", f"""
            SELECT count(*) FROM '{p(child)}' c
            WHERE c.{ccol} IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM '{p(parent)}' x WHERE x.{pcol} = c.{ccol})
        """))

    log.info("=" * 60)
    log.info("Primary IDs not null")
    log.info("=" * 60)
    for table, idcol in NOT_NULL_IDS:
        results.append(check(con, f"{table}.{idcol} NULLs",
                             f"SELECT count(*) FROM '{p(table)}' WHERE {idcol} IS NULL"))

    log.info("=" * 60)
    fails = sum(1 for r in results if r is False)
    if fails:
        log.error("%d check(s) FAILED", fails)
        sys.exit(1)
    log.info("All checks passed.")


if __name__ == "__main__":
    main()
