import { pool } from "../configs/db.js";

/* ================= CREATE ================= */
export const createAnalysis = async (userId, repoUrl) => {
    const res = await pool.query(
        `INSERT INTO analyses (user_id, repo_url, status)
         VALUES ($1, $2, 'pending')
         RETURNING *`,
        [userId, repoUrl]
    );
    return res.rows[0];
};

/* ================= UPDATE SUCCESS ================= */
export const updateAnalysis = async (id, result) => {
    await pool.query(
        `UPDATE analyses
         SET status='completed',
             result=$1,
             completed_at=NOW()
         WHERE id=$2`,
        [result, id]
    );
};

/* ================= UPDATE FAILURE ================= */
export const markFailed = async (id, error) => {
    await pool.query(
        `UPDATE analyses
         SET status='failed',
             result=$1
         WHERE id=$2`,
        [JSON.stringify({ error }), id]
    );
};

/* ================= GET ONE ================= */
export const getAnalysisById = async (id) => {
    const res = await pool.query(
        `SELECT * FROM analyses WHERE id=$1`,
        [id]
    );
    return res.rows[0];
};

/* ================= GET USER ================= */
export const getAnalysesByUser = async (userId) => {
    const res = await pool.query(
        `SELECT * FROM analyses
         WHERE user_id=$1
         ORDER BY created_at DESC`,
        [userId]
    );
    return res.rows;
};