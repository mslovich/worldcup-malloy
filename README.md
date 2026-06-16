# FIFA World Cup — Malloy + DuckDB

A [Malloy](https://www.malloydata.dev/) semantic model over the **Fjelstul World Cup
Database** — every men's (1930–2022) and women's (1991–2019) FIFA World Cup match,
goal, booking, squad and standing. Data is pulled as CSV, stored locally as Parquet,
and queried with DuckDB.

- **Source:** [datahub.io/football/worldcup](https://datahub.io/football/worldcup)
  (a mirror of [jfjelstul/worldcup](https://github.com/jfjelstul/worldcup))
- **License:** CC-BY-SA 4.0 — please credit the Fjelstul World Cup Database.

---

## Quick start

The data ships with the repo (`data/parquet/*.parquet`, ~1.5 MB, committed), so a
fresh clone works immediately — no download step:

```bash
# 1. Node deps for the Malloy runner
npm install

# 2. Run a query
npm run query -- "goals -> top_scorers"
npm run topscorers
```

**Refreshing the data is optional** — only needed to pull upstream updates or
regenerate from scratch (requires `pip install duckdb`):

```bash
python3 ingest.py     # re-download CSVs → data/parquet/*.parquet  (~25s)
python3 validate.py   # check referential integrity
```

---

## How the data is pulled

`ingest.py` is **datapackage-driven**. It reads datahub's
[`datapackage.json`](https://datahub.io/football/worldcup/_r/-/datapackage.json),
iterates the resources, and downloads each CSV via its permanent "r-link" URL
(`https://datahub.io/football/worldcup/_r/-/<file>.csv`) using DuckDB's `httpfs`
extension, writing one Parquet file per table.

Because the resource list comes from the live datapackage, **re-running picks up
upstream updates automatically** (new tournament editions, new/changed columns) — no
hardcoded table list to maintain.

```bash
python3 ingest.py                      # 27 core relational tables (default)
python3 ingest.py --include-summaries  # also the 9 pre-aggregated summary CSVs
python3 ingest.py --tables matches,goals
```

Raw CSVs are cached under `data/csv/`; typed Parquet lands in `data/parquet/`.
The `data/parquet/` files are **committed to the repo** (so clones and Malloy
Publisher work without an ingest step); the larger raw `data/csv/` cache is
git-ignored. Re-running `ingest.py` overwrites the Parquet in place — commit the
result to publish refreshed data.

---

## Tables (27 core)

| Group | Tables |
|---|---|
| **Lookups** | `tournaments`, `teams`, `players`, `stadiums`, `managers`, `referees`, `confederations` |
| **Match facts** | `matches`, `team_appearances`, `player_appearances`, `manager_appearances`, `referee_appearances` |
| **In-match events** | `goals`, `bookings`, `substitutions`, `penalty_kicks` |
| **Tournament structure** | `tournament_stages`, `groups`, `group_standings`, `tournament_standings`, `qualified_teams`, `host_countries` |
| **Rosters & people** | `squads`, `manager_appointments`, `referee_appointments` |
| **Awards** | `awards`, `award_winners` |

### Keys & joins

The data is **heavily denormalized** — most event tables already carry
`tournament_name`, `team_name`, `match_name` etc. inline, so you rarely need a join
just to read a label. The model adds joins so measures roll up cleanly.

Real join keys are the **domain IDs** (all `VARCHAR`, e.g. `WC-1930`):

```
matches            >── tournaments   ON tournament_id
                   >── stadiums      ON stadium_id
team_appearances   >── teams         ON team_id
                   >── tournaments   ON tournament_id
goals              >── matches       ON match_id
                   >── teams         ON team_id
                   >── players       ON player_id
bookings / subs / penalty_kicks  >── matches, teams, players
teams              >── confederations ON confederation_id
```

> Every table also has a `key_id` column — it's just a per-table row surrogate, **not**
> a cross-table key. The model uses it as a primary key only for bridge tables that
> have no single natural key (standings, squads, host_countries, …).

**Gotchas baked into the model:**
- `year` is a reserved word in Malloy — reference the column as `` tournaments.`year` ``
  (exposed as the `match_year` dimension on `matches`).
- Boolean-ish flags (`win`, `draw`, `own_goal`, `penalty`, `home_team_win`, …) are
  stored as `0/1` integers, so they `sum()` straight into counts.
- Mononym players (Marta, Pelé, Ronaldo) have `given_name = 'not applicable'`; the
  `full_name` / `scorer` dimensions handle this.

---

## The model

`worldcup.malloy` defines the sources, joins, measures and named views.
`explore.malloy` is a set of ready-to-run example analyses.

Some named views:

| Source | View | What it shows |
|---|---|---|
| `goals` | `top_scorers` | All-time top scorers (excl. own goals) |
| `goals` | `goals_by_minute` | Goal distribution across regulation minutes |
| `matches` | `by_tournament` | Matches / goals / avg goals per edition |
| `matches` | `highest_scoring` | Highest-scoring matches ever |
| `team_appearances` | `by_team` | Appearances, W/D/L, goals per nation |
| `team_appearances` | `by_confederation` | Same, rolled up by confederation |
| `bookings` | `by_tournament` | Cards / sending-offs per edition |

---

## Running queries

### Recommended: `run.mjs`

`run.mjs` compiles the model against DuckDB using the core
`@malloydata/malloy` + `@malloydata/db-duckdb` libraries:

```bash
node run.mjs "goals -> top_scorers"
node run.mjs "team_appearances -> by_team"
node run.mjs --model worldcup.malloy "matches -> highest_scoring"

# or via npm
npm run query -- "matches -> by_tournament"
```

### Malloy CLI / VS Code

`explore.malloy` contains `run:` statements meant for the official Malloy tooling:

- **VS Code:** install the *Malloy* extension and open `explore.malloy` — each
  `run:` gets a ▶ button.
- **CLI:** `npm run cli` (`malloy-cli run explore.malloy`).

> ⚠️ `malloy-cli@0.0.38` currently crashes on **Node ≥ 24** (a bundled HTTP-agent
> dependency throws at import). If you hit that, use `run.mjs` (works on any Node) or
> run the CLI under Node 20/22. The VS Code extension is unaffected.

---

## MCP server

`mcp_server.mjs` exposes the model to [MCP](https://modelcontextprotocol.io) clients
(Claude Code, Claude Desktop, etc.) over **stdio**. `.mcp.json` registers it as the
`worldcup` server, so a client that reads that file picks it up automatically; you can
also start it manually with `npm run mcp`.

It exposes **two** tools:

| Tool | What it does |
|---|---|
| `describe_model` | Returns the full `worldcup.malloy` source — sources, joins, measures, views. Call this first. |
| `run_malloy_query` | Runs a Malloy expression against the model, e.g. `"goals -> top_scorers"` or an ad-hoc `"matches -> { group_by: tournament_name; aggregate: match_count is count() }"`. |

**All queries go through the Malloy semantic model** — there is intentionally no
raw-SQL tool, so the agent can't bypass the model's joins, measures, and views.

Like the CLI runner, the server uses the core `@malloydata/*` libraries (no separate
process or port) and resolves `data/parquet/*` relative to its own location. Since the
Parquet is committed, it works from any clone with no ingest step.

---

## Project layout

```
worldcup/
├── ingest.py          # datapackage-driven CSV → Parquet
├── validate.py        # row-count + FK-coverage checks
├── worldcup.malloy    # the semantic model (sources, joins, measures, views)
├── explore.malloy     # example run: queries
├── run.mjs            # Node-26-proof query runner (uses @malloydata libs)
├── mcp_server.mjs     # stdio MCP server (describe_model + run_malloy_query)
├── .mcp.json          # registers the `worldcup` MCP server
├── publisher.json     # Malloy Publisher package manifest (name/version/description)
├── package.json       # npm scripts + Malloy deps
└── data/
    ├── csv/           # raw CSV cache (git-ignored, regenerable)
    └── parquet/       # one Parquet file per table (committed — ships with the repo)
```
