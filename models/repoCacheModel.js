import { pool } from "../configs/db.js";

// find cache by repo + branch + commit
export const findRepoCache = async (repoUrl, branch, commitSha) => {
const res = await pool.query(
`SELECT * FROM repo_cache
         WHERE repo_url = $1
         AND branch = $2
         AND commit_sha = $3`,
[repoUrl, branch, commitSha]
);
return res.rows[0];
};

// upsert cache (insert or update)
export const upsertRepoCache = async (
repoUrl,
branch,
commitSha,
result
) => {
await pool.query(
`INSERT INTO repo_cache (repo_url, branch, commit_sha, result)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (repo_url, branch, commit_sha)
         DO UPDATE SET
            result = EXCLUDED.result,
            run_count = repo_cache.run_count + 1,
            last_analyzed = NOW()`,
[repoUrl, branch, commitSha, result]
);
};
