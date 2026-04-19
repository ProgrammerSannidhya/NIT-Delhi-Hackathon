// models/userModel.js

import { pool } from "../configs/db.js";

/* ================= FIND ================= */
export const findUserByUsername = async (username) => {
    const result = await pool.query(
        `SELECT * FROM users WHERE username = $1`,
        [username]
    );

    return result.rows[0];
};

/* ================= CREATE ================= */
export const createUser = async ({ username, password, role = "user" }) => {
    const result = await pool.query(
        `INSERT INTO users (username, password, role)
        VALUES ($1, $2, $3)
        RETURNING id, username, role`,
        [username, password, role]
    );

    return result.rows[0];
};

/* ================= LOGIN TRACKING ================= */
export const incrementFailedAttempts = async (userId) => {
    await pool.query(
        `UPDATE users
        SET failed_attempts = failed_attempts + 1
        WHERE id = $1`,
        [userId]
    );
};

export const resetFailedAttempts = async (userId) => {
    await pool.query(
        `UPDATE users
        SET failed_attempts = 0,
            lock_until = NULL
        WHERE id = $1`,
        [userId]
    );
};

export const lockUser = async (userId, lockTime) => {
    await pool.query(
        `UPDATE users
        SET lock_until = $1
        WHERE id = $2`,
        [lockTime, userId]
    );
};