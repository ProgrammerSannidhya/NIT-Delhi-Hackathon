// controllers/authController.js

import {
    registerUser,
    loginUser
} from "../services/authServices.js";

import {
    generateAccessToken,
    generateRefreshToken,
    verifyToken
} from "../utils/jwt.js";

import {
    createRefreshToken,
    findRefreshToken,
    deleteRefreshToken,
    rotateRefreshToken
} from "../models/tokenModel.js";

import { success, fail } from "../utils/response.js";

/* ================= REGISTER ================= */
export const register = async (req, res, next) => {
try {
if (!req.body) {
return res.status(400).json({
error: "Request body missing"
});
}


    const { username, password } = req.body;

    if (!username || !password) {
        return res.status(400).json({
            error: "username and password required"
        });
    }

    const user = await registerUser(username, password);

    return success(res, user, "User registered", 201);

} catch (err) {
    next(err);
}


};

/* ================= LOGIN ================= */
export const login = async (req, res, next) => {
    try {
        const { username, password } = req.body;

        const user = await loginUser(username, password);

        if (!user) {
            return fail(res, "Invalid credentials", 401);
        }

        const accessToken = generateAccessToken(user);
        const refreshToken = generateRefreshToken(user);

        const expiresAt = new Date();
        expiresAt.setDate(expiresAt.getDate() + 7);

        await createRefreshToken(user.id, refreshToken, expiresAt);

        return success(res, {
            accessToken,
            refreshToken
        }, "Login successful");

    } catch (err) {
        next(err);
    }
};

/* ================= REFRESH (ROTATION) ================= */
export const refresh = async (req, res, next) => {
        if (!req.body || typeof req.body !== "object") {
    return res.status(400).json({
        error: "Request body is missing or not JSON. Set Content-Type: application/json."
    });
}
    try {
        const { token } = req.body;

        if (!token) {
            return fail(res, "Refresh token required", 400);
        }

        const stored = await findRefreshToken(token);

        if (!stored) {
            return fail(res, "Invalid refresh token", 403);
        }

        const decoded = verifyToken(token);

        const newAccessToken = generateAccessToken({
            id: decoded.id,
            role: decoded.role || "user"
        });

        const newRefreshToken = generateRefreshToken({
            id: decoded.id
        });

        const expiresAt = new Date();
        expiresAt.setDate(expiresAt.getDate() + 7);

        await rotateRefreshToken(token, newRefreshToken, expiresAt);

        return success(res, {
            accessToken: newAccessToken,
            refreshToken: newRefreshToken
        }, "Token rotated");

    } catch (err) {
        next(err);
    }
};

/* ================= LOGOUT ================= */
export const logout = async (req, res, next) => {
    try {
        const { token } = req.body;

        if (!token) {
            return fail(res, "Token required", 400);
        }

        await deleteRefreshToken(token);

        return success(res, null, "Logged out");

    } catch (err) {
        next(err);
    }
};

/* ================= GET ME ================= */
export const getMe = async (req, res, next) => {
    try {
        return success(res, req.user, "Authenticated user");
    } catch (err) {
        next(err);
    }
};