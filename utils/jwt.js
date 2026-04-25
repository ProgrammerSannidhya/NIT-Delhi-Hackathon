// utils/jwt.js

import jwt from "jsonwebtoken";

/* ================= ACCESS TOKEN ================= */
export const generateAccessToken = (user) => {
    return jwt.sign(
        {
            id: user.id,
            role: user.role
        },
        process.env.JWT_SECRET,
        {
            expiresIn: "60m"
        }
    );
};

/* ================= REFRESH TOKEN ================= */
export const generateRefreshToken = (user) => {
    return jwt.sign(
        {
            id: user.id
        },
        process.env.JWT_SECRET,
        {
            expiresIn: "7d"
        }
    );
};

/* ================= VERIFY TOKEN ================= */
export const verifyToken = (token) => {
    return jwt.verify(token, process.env.JWT_SECRET);
};