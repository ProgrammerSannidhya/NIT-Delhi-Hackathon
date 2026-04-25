import { pool } from "../configs/db.js";

/* ================= CREATE ================= */
export const createAnalysis = async (userId, repoUrl) => {
    const res = await pool.query(
        `INSERT INTO analyses (user_id, repo_url, status)
         VALUES ($1, $2, 'queued')
         RETURNING *`,
        [userId, repoUrl]
    );
    return res.rows[0];
};

/* ================= GENERIC UPDATE ================= */
export const updateAnalysis = async (id, fields) => {
    const keys = Object.keys(fields);

    if (keys.length === 0) return;

    const setClause = keys
        .map((key, i) => `${key} = $${i + 1}`)
        .join(", ");

    const values = Object.values(fields);

    await pool.query(
        `UPDATE analyses SET ${setClause} WHERE id = $${keys.length + 1}`,
        [...values, id]
    );
};

/* ================= GET ONE (WITH USER CHECK) ================= */
export const getAnalysisById = async (id, userId = null) => {
    let res;

    if (userId) {
        res = await pool.query(
            `SELECT * FROM analyses WHERE id = $1 AND user_id = $2`,
            [id, userId]
        );
    } else {
        res = await pool.query(
            `SELECT * FROM analyses WHERE id = $1`,
            [id]
        );
    }

    return res.rows[0];
};

/* ================= GET USER ================= */
export const getAnalysesByUser = async (userId) => {
    const res = await pool.query(
        `SELECT * FROM analyses
         WHERE user_id = $1
         ORDER BY created_at DESC`,
        [userId]
    );
    return res.rows;
};