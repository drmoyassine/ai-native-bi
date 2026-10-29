// Cube's configuration (docs/data-model-spec.md section 10, M0b). The model comes from two places: files in model/ (hand-written,
// reviewed by pull request) and the files the BI writes into its database (cube_model.file: an installed template's files now, the
// builders' generated cubes later). Cube re-reads the model when those files change (schemaVersion). It reads with its own role, which
// may read analytics and these files only (CLAUDE.md rule 5).
const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');

const pool = new Pool({
  host: process.env.CUBEJS_DB_HOST,
  port: Number(process.env.CUBEJS_DB_PORT || 5432),
  user: process.env.CUBEJS_DB_USER,
  password: process.env.CUBEJS_DB_PASS,
  database: process.env.CUBEJS_DB_NAME,
  ssl: process.env.CUBEJS_DB_SSL === 'true' ? { rejectUnauthorized: false } : undefined,
  max: 2,
});

// Before the BI has migrated its database the table does not exist yet: then there are no written files.
const MISSING = new Set(['42P01', '3F000', '42501']);

async function written() {
  try {
    const { rows } = await pool.query('select name, content from cube_model.file order by name');
    return rows.map((r) => ({ fileName: `written/${r.name}`, content: r.content }));
  } catch (e) {
    if (MISSING.has(e.code)) return [];
    throw e;
  }
}

function handWritten(dir = path.join(__dirname, 'model'), base = dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return handWritten(full, base);
    if (!/\.(ya?ml|js)$/.test(entry.name)) return [];
    return [{ fileName: path.relative(base, full), content: fs.readFileSync(full, 'utf8') }];
  });
}

module.exports = {
  repositoryFactory: () => ({
    dataSchemaFiles: async () => [...handWritten(), ...(await written())],
  }),
  schemaVersion: async () => {
    try {
      const { rows } = await pool.query("select count(*) || ':' || coalesce(max(updated_at)::text, '') as v from cube_model.file");
      return rows[0].v;
    } catch (e) {
      if (MISSING.has(e.code)) return 'none';
      throw e;
    }
  },
};
