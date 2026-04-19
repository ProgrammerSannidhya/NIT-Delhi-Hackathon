import { pool } from "../configs/db.js";

// CREATE USER
export const createUserService = async (name) => {
    const result = await pool.query(
        "INSERT INTO users (username) VALUES ($1) RETURNING *",
        [name]
    );
    return result.rows[0];
};

// GET ALL USERS
export const GetAllUsersService = async () => {
    const result = await pool.query("SELECT * FROM users");
    return result.rows;
};

// GET USER BY ID
export const GetUserByIdService = async (id) => {
    const result = await pool.query(
        "SELECT * FROM users WHERE id = $1",
        [id]
    );
    return result.rows[0];
};

// UPDATE USER
export const UpdateUserService = async (id, name) => {
    const result = await pool.query(
        `UPDATE users SET username = $1 WHERE id = $2 RETURNING *`,
        [name, id]
    );
    return result.rows[0];
};

// DELETE USER
export const DeleteUserService = async (id) => {
    const result = await pool.query(
        "DELETE FROM users WHERE id = $1 RETURNING *",
        [id]
    );
    return result.rows[0];
};