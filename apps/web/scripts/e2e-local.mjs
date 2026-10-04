import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
const keys = JSON.parse(
  readFileSync(
    new URL(
      "../../../services/agent-followup/.local-pilot-keys.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const result = spawnSync("npm", ["run", "test:e2e"], {
  stdio: "inherit",
  env: { ...process.env, E2E_ACCESS_KEY: keys.admin },
});
process.exit(result.status ?? 1);
