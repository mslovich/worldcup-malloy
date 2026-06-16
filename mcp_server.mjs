// Local stdio MCP server for the FIFA World Cup Malloy model.
//
// Exposes the worldcup.malloy semantic model to Claude (or any MCP client) as
// two tools:
//   • run_malloy_query — run a Malloy query against the model (e.g. "goals -> top_scorers")
//   • describe_model   — return the model source so the agent knows what's queryable
//
// Queries go exclusively through the Malloy semantic model — there is no raw-SQL
// tool, so the agent can't bypass the model's joins, measures, and views.
//
// Uses the core @malloydata/* libraries (which work on current Node), so there's
// no separate server process or port — Claude Code launches this over stdio.
//
// IMPORTANT: a stdio MCP server must keep stdout clean for the protocol. All
// diagnostics go to stderr (console.error), never console.log.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import malloy from "@malloydata/malloy";
import duckdb from "@malloydata/db-duckdb";

const { SingleConnectionRuntime } = malloy;
const { DuckDBConnection } = duckdb;

// Resolve paths relative to this file so `data/parquet/*` works no matter where
// the server is launched from.
const HERE = dirname(fileURLToPath(import.meta.url));
process.chdir(HERE);

const MODEL_FILE = "worldcup.malloy";
const modelSrc = () => readFileSync(MODEL_FILE, "utf-8");

const connection = new DuckDBConnection("duckdb");
const runtime = new SingleConnectionRuntime({ connection });

// DuckDB sums come back as BigInt — make results JSON-serializable.
const clean = (rows) =>
  rows.map((r) =>
    Object.fromEntries(
      Object.entries(r).map(([k, v]) => [k, typeof v === "bigint" ? Number(v) : v])
    )
  );

const server = new McpServer({ name: "worldcup", version: "1.0.0" });

server.registerTool(
  "run_malloy_query",
  {
    title: "Run a Malloy query",
    description:
      "Run a Malloy query against the World Cup model (worldcup.malloy). " +
      "Pass the query expression that would follow `run:`, e.g. " +
      "\"goals -> top_scorers\", \"team_appearances -> by_team\", or an ad-hoc " +
      "query like \"matches -> { group_by: tournament_name; aggregate: match_count is count() }\". " +
      "Call describe_model first to see available sources, measures, and views.",
    inputSchema: {
      query: z.string().describe("Malloy query expression (the part after `run:`)"),
      limit: z.number().int().positive().optional().describe("Max rows to return (default 1000)"),
    },
  },
  async ({ query, limit }) => {
    try {
      const result = await runtime
        .loadQuery(`${modelSrc()}\n\nrun: ${query}\n`)
        .run({ rowLimit: limit ?? 1000 });
      const rows = clean(result.data.toObject());
      return {
        content: [
          {
            type: "text",
            text:
              `${rows.length} row(s).\n\n` +
              JSON.stringify(rows, null, 2) +
              `\n\n-- Generated SQL --\n${result.sql}`,
          },
        ],
      };
    } catch (e) {
      return { isError: true, content: [{ type: "text", text: `Malloy error:\n${e?.message ?? e}` }] };
    }
  }
);

server.registerTool(
  "describe_model",
  {
    title: "Describe the World Cup model",
    description:
      "Return the full worldcup.malloy source — all sources, joins, measures, and " +
      "named views — so you know what can be queried with run_malloy_query.",
    inputSchema: {},
  },
  async () => ({ content: [{ type: "text", text: modelSrc() }] })
);

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("[worldcup-mcp] ready (stdio)");
