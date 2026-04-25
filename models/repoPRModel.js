import { pool } from "../configs/db.js";

/* ---------------- FIND ---------------- */
export const findExistingPR = async (repoUrl, commitSha) => {
    const res = await pool.query(
        `SELECT * FROM repo_pr_tracking
         WHERE repo_url = $1 AND commit_sha = $2`,
        [repoUrl, commitSha]
    );

    return res.rows[0];
};

/* ---------------- CREATE ---------------- */
export const createPRRecord = async ({
    repoUrl,
    commitSha,
    forkUrl,
    branch,
    prUrl
}) => {
    const res = await pool.query(
        `INSERT INTO repo_pr_tracking 
        (repo_url, commit_sha, fork_url, branch, pr_url, status)
        VALUES ($1, $2, $3, $4, $5, 'created')
        RETURNING *`,
        [repoUrl, commitSha, forkUrl, branch, prUrl]
    );

    return res.rows[0];
};

/* ---------------- UPDATE ---------------- */
export const updatePRRecord = async (repoUrl, commitSha, fields) => {
    const keys = Object.keys(fields);

    if (keys.length === 0) return;

    const setClause = keys
        .map((k, i) => `${k} = $${i + 1}`)
        .join(", ");

    const values = Object.values(fields);

    await pool.query(
        `UPDATE repo_pr_tracking 
         SET ${setClause}, updated_at = NOW()
         WHERE repo_url = $${keys.length + 1}
         AND commit_sha = $${keys.length + 2}`,
        [...values, repoUrl, commitSha]
    );
};