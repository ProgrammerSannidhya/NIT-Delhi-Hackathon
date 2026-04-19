// models/tokenModel.js

import { pool } from "../configs/db.js";

/* ================= CREATE ================= */
export const createRefreshToken = async (userId, token, expiresAt) => {
    const result = await pool.query(
        `INSERT INTO refresh_tokens (user_id, token, expires_at)
         VALUES ($1, $2, $3)
         RETURNING *`,
        [userId, token, expiresAt]
    );

    return result.rows[0];
};

/* ================= FIND ================= */
export const findRefreshToken = async (token) => {
    const result = await pool.query(
        `SELECT * FROM refresh_tokens WHERE token = $1`,
        [token]
    );

    return result.rows[0];
};

/* ================= DELETE ONE ================= */
export const deleteRefreshToken = async (token) => {
    await pool.query(
        `DELETE FROM refresh_tokens WHERE token = $1`,
        [token]
    );
};

/* ================= ROTATE ================= */
export const rotateRefreshToken = async (oldToken, newToken, expiresAt) => {
    const client = await pool.connect();

    try {
        await client.query("BEGIN");

        const old = await client.query(
            `SELECT * FROM refresh_tokens WHERE token = $1`,
            [oldToken]
        );

        if (!old.rows[0]) {
            throw new Error("Invalid refresh token");
        }

        const userId = old.rows[0].user_id;

        // delete old token
        await client.query(
            `DELETE FROM refresh_tokens WHERE token = $1`,
            [oldToken]
        );

        // insert new token
        const inserted = await client.query(
            `INSERT INTO refresh_tokens (user_id, token, expires_at)
             VALUES ($1, $2, $3)
             RETURNING *`,
            [userId, newToken, expiresAt]
        );

        await client.query("COMMIT");

        return inserted.rows[0];

    } catch (err) {
        await client.query("ROLLBACK");
        throw err;
    } finally {
        client.release();
    }
};