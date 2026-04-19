import {
    createUserService,
    GetAllUsersService,
    GetUserByIdService,
    UpdateUserService,
    DeleteUserService
} from "../services/userServices.js";

import { success, fail } from "../utils/response.js";

/* ================= CREATE ================= */
export const createUser = async (req, res, next) => {
    try {
        const { username } = req.body;

        const user = await createUserService(username);

        return success(res, user, "User created", 201);

    } catch (err) {
        if (err.code === "23505") {
            return fail(res, "Username already exists", 400);
        }
        next(err);
    }
};

/* ================= GET ALL ================= */
export const getAllUsers = async (req, res, next) => {
    try {
        const users = await GetAllUsersService();

        return success(res, users, "Users fetched");

    } catch (err) {
        next(err);
    }
};

/* ================= GET BY ID ================= */
export const getUserById = async (req, res, next) => {
    try {
        const { id } = req.params;

        const user = await GetUserByIdService(id);

        if (!user) {
            return fail(res, "User not found", 404);
        }

        return success(res, user, "User fetched");

    } catch (err) {
        next(err);
    }
};

/* ================= UPDATE ================= */
export const updateUser = async (req, res, next) => {
    try {
        const { id } = req.params;
        const { username } = req.body;

        const updated = await UpdateUserService(id, username);

        if (!updated) {
            return fail(res, "User not found", 404);
        }

        return success(res, updated, "User updated");

    } catch (err) {
        next(err);
    }
};

/* ================= DELETE ================= */
export const deleteUser = async (req, res, next) => {
    try {
        const { id } = req.params;

        const deleted = await DeleteUserService(id);

        if (!deleted) {
            return fail(res, "User not found", 404);
        }

        return success(res, deleted, "User deleted");

    } catch (err) {
        next(err);
    }
};