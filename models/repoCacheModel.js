import { pool } from "../configs/db.js";

export const findRepoCache = async (repoUrl) => {
    const res = await pool.query(
        `SELECT * FROM repo_cache WHERE LOWER(repo_url) = LOWER($1)`,
        [repoUrl]
    );
    return res.rows[0];
};

export const upsertRepoCache = async (repoUrl, result) => {
    await pool.query(
        `INSERT INTO repo_cache (repo_url, result)
         VALUES ($1, $2)
         ON CONFLICT (repo_url)
         DO UPDATE SET
            result = EXCLUDED.result,
            run_count = repo_cache.run_count + 1,
            last_analyzed = NOW()`,
        [repoUrl, result]
    );
};