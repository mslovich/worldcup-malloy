#!/usr/bin/env python3
"""
FIFA World Cup (Fjelstul World Cup Database) → Parquet ingest.

Datapackage-driven: reads datahub.io's `datapackage.json` for the dataset,
iterates its resources, and pulls each CSV directly via its permanent
"r-link" URL using DuckDB's httpfs extension, writing one Parquet file per
table. Because the resource list comes from the live datapackage, re-running
automatically picks up upstream updates (new editions, new/changed columns).

Scope: the 27 core relational tables. The 9 pre-aggregated "summary"/derived
CSVs (top-scorers-summary, dirtiest-matches-summary, attendance*, etc.) are
skipped by default — Malloy reproduces those from the base tables. Pass
--include-summaries to pull everything.

Usage:
    python3 ingest.py [--output-dir ./data/parquet] [--tables matches,goals,...]
    python3 ingest.py --include-summaries        # all 36 resources

Idempotent: re-running overwrites existing Parquet files cleanly.
"""

import argparse
import json
import logging
import time
import urllib.request
from pathlib import Path

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# datahub.io permanent "r-link" URLs — stable, safe to hardcode.
DATAPACKAGE_URL = "https://datahub.io/football/worldcup/_r/-/datapackage.json"
RLINK = "https://datahub.io/football/worldcup/_r/-/{path}"

# Resource-name substrings that mark a pre-aggregated / derived table.
# Skipped unless --include-summaries is passed.
SUMMARY_MARKERS = ("summary", "attendance", "top-scorers", "tournament-appearances")


def is_core(name: str) -> bool:
    """True for the 27 base relational tables (not a derived summary)."""
    return not any(m in name for m in SUMMARY_MARKERS)


def load_resources(include_summaries: bool) -> list[dict]:
    """Fetch the datapackage and return the resources we want to ingest."""
    log.info("Fetching datapackage → %s", DATAPACKAGE_URL)
    with urllib.request.urlopen(DATAPACKAGE_URL) as resp:
        pkg = json.load(resp)

    resources = []
    for r in pkg.get("resources", []):
        name = r.get("name")
        path = r.get("path")
        if not name or not path or not path.endswith(".csv"):
            continue
        if not include_summaries and not is_core(name):
            continue
        # Normalise the Parquet/table name (resource names are already snake/kebab).
        resources.append({"name": name.replace("-", "_"), "path": path, "url": RLINK.format(path=path)})

    log.info("datapackage lists %d ingestable resource(s)", len(resources))
    return resources


def write_table(con: duckdb.DuckDBPyConnection, res: dict, out_dir: Path, csv_dir: Path) -> int:
    """Cache the raw CSV locally, then write it to Parquet via DuckDB."""
    name, url = res["name"], res["url"]
    out_path = out_dir / f"{name}.parquet"
    csv_path = csv_dir / res["path"]

    log.info("[%s] Downloading CSV …", name)
    t0 = time.time()
    urllib.request.urlretrieve(url, csv_path)

    # read_csv_auto sniffs types from the CSV header + sample.
    con.execute(
        f"COPY (SELECT * FROM read_csv_auto('{csv_path}', header=true)) "
        f"TO '{out_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    count = con.execute(f"SELECT count(*) FROM '{out_path}'").fetchone()[0]
    log.info("[%s] Done — %s rows in %.1fs", name, f"{count:,}", time.time() - t0)
    return count


def main():
    parser = argparse.ArgumentParser(description="FIFA World Cup → Parquet ingest")
    parser.add_argument("--output-dir", default="./data/parquet",
                        help="Directory to write Parquet files (default: ./data/parquet)")
    parser.add_argument("--csv-dir", default="./data/csv",
                        help="Directory to cache raw CSVs (default: ./data/csv)")
    parser.add_argument("--tables", default=None,
                        help="Comma-separated subset of resource names to pull (default: all core)")
    parser.add_argument("--include-summaries", action="store_true",
                        help="Also ingest the pre-aggregated summary/derived CSVs")
    parser.add_argument("--memory-limit", default="4GB",
                        help="DuckDB memory limit (default: 4GB)")
    parser.add_argument("--threads", type=int, default=4,
                        help="DuckDB thread count (default: 4)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    csv_dir = Path(args.csv_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    resources = load_resources(args.include_summaries)

    if args.tables:
        wanted = {t.strip().replace("-", "_") for t in args.tables.split(",")}
        available = {r["name"] for r in resources}
        unknown = wanted - available
        if unknown:
            parser.error(f"Unknown tables: {sorted(unknown)}. Valid: {sorted(available)}")
        resources = [r for r in resources if r["name"] in wanted]

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET threads={args.threads}")

    totals = {}
    wall_start = time.time()
    for res in resources:
        totals[res["name"]] = write_table(con, res, out_dir, csv_dir)

    log.info("─" * 60)
    log.info("All done in %.1fs — %d tables", time.time() - wall_start, len(totals))
    for name, count in sorted(totals.items()):
        log.info("  %-22s %s rows", name, f"{count:,}")


if __name__ == "__main__":
    main()
