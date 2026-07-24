// ATLAS Visual Intelligence Foundation -- bounded DuckDB-Wasm service.
//
// Security and lifecycle model (see docs/visual-intelligence/DUCKDB_LIFECYCLE_AND_SECURITY.md):
//  - Lazy: the @duckdb/duckdb-wasm package itself is dynamically imported inside initialize(),
//    not statically at module load, so it lands in its own Rollup chunk separate from the rest
//    of the Visual Intelligence Lab bundle -- Prototypes 2 and 3 (which never call initialize())
//    never fetch it, and even Prototype 1 only fetches it once a query actually needs DuckDB-Wasm
//    (rows above largeDataPolicy.ts's DIRECT_RENDER_MAX), not merely on mount.
//  - Self-hosted, not CDN: the worker/wasm assets are imported via Vite's `?url` asset handling
//    from the already-installed @duckdb/duckdb-wasm package, so they are served from ATLAS's own
//    origin. No <script src="https://cdn..."> tag, no runtime fetch to a third-party host.
//  - Worker-isolated: every query runs inside the Web Worker DuckDB-Wasm itself creates; the main
//    thread only awaits promises, so a slow/large query cannot block UI rendering.
//  - Explicitly registered data only: registerTable() is the ONLY way data enters this database,
//    and every caller must go through the Data Access Layer (dataAccessLayer.ts), which is the
//    place that enforces "this data belongs to the authenticated user's current project." This
//    service itself does not call the backend, read cookies, or resolve identity -- it has no
//    ambient authorization of its own, by design, so it cannot be a bypass of backend authorization.
//  - No file access, no network, no remote extensions: DuckDB-Wasm's default browser build has no
//    filesystem or network I/O surface; this service never calls `LOAD` or `INSTALL` for any
//    extension, and never opens a remote HTTP-backed table.
//  - Per-scope isolation: registered tables are named `${projectId}__${tableName}` and
//    clearProjectTables(projectId) drops every table for that project. Callers (project switch,
//    sign-out, dataset-version change, component unmount) are responsible for invoking it -- see
//    the call sites in dataAccessLayer.ts and the prototype components' cleanup effects.
import type * as duckdb from "@duckdb/duckdb-wasm";
import duckdbWasmMvp from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import duckdbWasmEh from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import duckdbWorkerMvp from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import duckdbWorkerEh from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";

export type DuckDbQueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  queryDurationMs: number;
};

let dbInstance: duckdb.AsyncDuckDB | null = null;
let dbInitPromise: Promise<duckdb.AsyncDuckDB> | null = null;
let connInstance: duckdb.AsyncDuckDBConnection | null = null;
const registeredTables = new Set<string>();

async function initialize(): Promise<duckdb.AsyncDuckDB> {
  if (dbInstance) return dbInstance;
  if (dbInitPromise) return dbInitPromise;

  dbInitPromise = (async () => {
    const duckdbModule = await import("@duckdb/duckdb-wasm");
    const bundles: duckdb.DuckDBBundles = {
      mvp: { mainModule: duckdbWasmMvp, mainWorker: duckdbWorkerMvp },
      eh: { mainModule: duckdbWasmEh, mainWorker: duckdbWorkerEh },
    };
    const bundle = await duckdbModule.selectBundle(bundles);
    if (!bundle.mainWorker) throw new Error("DuckDB-Wasm: no compatible worker bundle for this browser.");

    const worker = new Worker(bundle.mainWorker);
    const logger = new duckdbModule.ConsoleLogger(duckdbModule.LogLevel.WARNING);
    const db = new duckdbModule.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    dbInstance = db;
    return db;
  })();

  return dbInitPromise;
}

async function getConnection(): Promise<duckdb.AsyncDuckDBConnection> {
  const db = await initialize();
  if (!connInstance) connInstance = await db.connect();
  return connInstance;
}

function scopedTableName(projectId: string, tableName: string): string {
  // Identifiers cannot be parameterized in SQL; this name is never built from
  // user-supplied free text (callers pass a fixed literal like "distribution_source"),
  // and projectId is a backend-issued id (server/persistence/repositories/project_repository.py),
  // not client-controlled free text -- but as defense in depth, strip anything that
  // isn't alphanumeric/underscore before it ever reaches a SQL statement.
  const safeProject = projectId.replace(/[^a-zA-Z0-9_]/g, "_");
  const safeTable = tableName.replace(/[^a-zA-Z0-9_]/g, "_");
  return `t_${safeProject}__${safeTable}`;
}

/** Register a bounded, already-fetched set of rows as a queryable table. This is the
 *  ONLY ingestion path -- there is no file-open or URL-fetch entry point on this service.
 *  Rows must already have been approved by the Data Access Layer (size-checked against
 *  largeDataPolicy.ts and authorization-checked against the current project/user). */
export async function registerTable(projectId: string, tableName: string, rows: Record<string, unknown>[]): Promise<string> {
  const db = await initialize();
  const scoped = scopedTableName(projectId, tableName);
  const json = new TextEncoder().encode(JSON.stringify(rows));
  await db.registerFileBuffer(`${scoped}.json`, json);
  const conn = await getConnection();
  await conn.query(`DROP TABLE IF EXISTS ${scoped}`);
  await conn.query(`CREATE TABLE ${scoped} AS SELECT * FROM read_json_auto('${scoped}.json')`);
  registeredTables.add(scoped);
  return scoped;
}

/** Run a read-only query against previously-registered tables. Callers build the SQL
 *  text themselves (this module doesn't accept raw user text as a query), but any
 *  user-controlled VALUE (a filter threshold, a selected category) must be passed via
 *  `params` and interpolated through DuckDB's own prepared-statement parameter binding,
 *  never string-concatenated into the query text. */
export async function runQuery(sql: string, params: unknown[] = []): Promise<DuckDbQueryResult> {
  const conn = await getConnection();
  const start = performance.now();
  const statement = await conn.prepare(sql);
  try {
    const result = params.length ? await statement.query(...params) : await statement.query();
    const columns = result.schema.fields.map((field) => field.name);
    const rows = result.toArray().map((row) => row.toJSON() as Record<string, unknown>);
    return { columns, rows, rowCount: rows.length, queryDurationMs: performance.now() - start };
  } finally {
    await statement.close();
  }
}

/** Drop every table registered for one project -- called on project switch, sign-out,
 *  dataset-version change, and visualization disposal (see call sites for each). */
export async function clearProjectTables(projectId: string): Promise<void> {
  if (!connInstance) return;
  const prefix = `t_${projectId.replace(/[^a-zA-Z0-9_]/g, "_")}__`;
  const toDrop = Array.from(registeredTables).filter((name) => name.startsWith(prefix));
  for (const name of toDrop) {
    await connInstance.query(`DROP TABLE IF EXISTS ${name}`);
    registeredTables.delete(name);
  }
}

/** Full teardown -- releases the worker and wasm instance. Call on sign-out or when no
 *  visualization needing DuckDB-Wasm remains mounted anywhere in the app. */
export async function disposeDuckDb(): Promise<void> {
  if (connInstance) {
    await connInstance.close();
    connInstance = null;
  }
  if (dbInstance) {
    await dbInstance.terminate();
    dbInstance = null;
  }
  dbInitPromise = null;
  registeredTables.clear();
}

export function isDuckDbInitialized(): boolean {
  return dbInstance !== null;
}
