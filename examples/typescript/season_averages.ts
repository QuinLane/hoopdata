// Print player season averages from a hoopdata data root.
//
//     cd examples/typescript
//     npm install
//     node season_averages.ts [DATA_ROOT]
//
// DATA_ROOT defaults to $NBA_DATA_ROOT, then ./data.
// Needs Node 22.18 or newer, which runs TypeScript files directly.

import path from "node:path";
import { DuckDBInstance } from "@duckdb/node-api";

const dataRoot = process.argv[2] || process.env.NBA_DATA_ROOT || "data";

const instance = await DuckDBInstance.create(path.join(dataRoot, "hoopdata.duckdb"), {
  access_mode: "READ_ONLY",
});
const con = await instance.connect();
const reader = await con.runAndReadAll(`
  select season, season_type, player_name, games_played, pts, reb, ast, fg_pct
  from player_season_averages
  where games_played >= 20
  order by pts desc
  limit 20
`);
con.closeSync();
instance.closeSync();

console.table(reader.getRowObjectsJson());
