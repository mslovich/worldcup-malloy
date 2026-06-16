// Minimal Malloy query runner — compiles a .malloy model against DuckDB and
// prints the result of a query as a table.
//
// Why this exists: the bundled `malloy-cli` binary currently fails to load on
// very recent Node versions (a transitive HTTP-agent dependency throws at
// import time). This script uses the core @malloydata/malloy +
// @malloydata/db-duckdb libraries directly, which are unaffected.
//
// Usage:
//   node run.mjs "<query>"                  e.g. node run.mjs "goals -> top_scorers"
//   node run.mjs --model worldcup.malloy "team_appearances -> by_team"
//
// The model's `duckdb.table('data/parquet/…')` paths resolve relative to the
// current working directory, so run this from the project root.

import { readFileSync } from "node:fs";
import malloy from "@malloydata/malloy";
import duckdb from "@malloydata/db-duckdb";

const { SingleConnectionRuntime } = malloy;
const { DuckDBConnection } = duckdb;

const args = process.argv.slice(2);
let model = "worldcup.malloy";
const positional = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--model") model = args[++i];
  else positional.push(args[i]);
}
const query = positional.join(" ").trim();
if (!query) {
  console.error('Usage: node run.mjs [--model worldcup.malloy] "<malloy query>"');
  process.exit(1);
}

const connection = new DuckDBConnection("duckdb");
const runtime = new SingleConnectionRuntime({ connection });

// Inline the model source and append the query — avoids any URL-reader setup.
const modelSrc = readFileSync(model, "utf-8");
const fullSrc = `${modelSrc}\n\nrun: ${query}\n`;

try {
  const result = await runtime.loadQuery(fullSrc).run();
  // DuckDB sums come back as BigInt; coerce to Number for clean table output.
  const rows = result.data.toObject().map((row) =>
    Object.fromEntries(
      Object.entries(row).map(([k, v]) => [k, typeof v === "bigint" ? Number(v) : v])
    )
  );
  if (!rows.length) console.log("(no rows)");
  else console.table(rows);
} catch (e) {
  console.error("Query failed:\n", e?.message ?? e);
  process.exitCode = 1;
} finally {
  await connection.close();
}
