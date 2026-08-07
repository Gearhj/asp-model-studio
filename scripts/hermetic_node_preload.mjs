/** Fail-closed pre-import validation for every hermetic Node test child. */
import process from "node:process";

import { validateConfig } from "./hermetic_node_guard.mjs";

try {
  validateConfig(process.env);
  process.env.ATLAS_HERMETIC_NODE_GUARD_PASSED = "1";
} catch (error) {
  process.stderr.write(`${error?.message || "HERMETIC_NODE_GUARD_REJECTED:unknown"}\n`);
  process.exit(86);
}
