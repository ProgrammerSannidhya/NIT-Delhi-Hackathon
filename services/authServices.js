// services/authServices.js

import bcrypt from "bcrypt";
import {
    createUser,
    findUserByUsername,
    incrementFailedAttempts,
    resetFailedAttempts,
    lockUser
} from "../models/userModel.js";

const MAX_ATTEMPTS = 5;
const LOCK_TIME_MINUTES = 15;

/* ================= PASSWORD POLICY ================= */
const validatePassword = (password) => {
    if (typeof password !== "string") return false;

    if (password.length < 8) return false;

    const hasUpper = /[A-Z]/.test(password);
    const hasLower = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);

    return hasUpper && hasLower && hasNumber;
};

/* ================= REGISTER ================= */
export const registerUser = async (username, password) => {
    if (!validatePassword(password)) {
        throw new Error(
            "Password must be 8+ chars with upper, lower, number"
        );
    }

    const hashed = await bcrypt.hash(password, 10);

    return createUser({ username, password: hashed });
};

/* ================= LOGIN ================= */
export const loginUser = async (username, password) => {
    const user = await findUserByUsername(username);

    if (!user) return null;

    /* LOCK CHECK */
    if (user.lock_until && new Date(user.lock_until) > new Date()) {
        throw new Error("Account locked. Try later.");
    }

    const match = await bcrypt.compare(password, user.password);

    if (!match) {
        await incrementFailedAttempts(user.id);

        if (user.failed_attempts + 1 >= MAX_ATTEMPTS) {
            const lockTime = new Date();
            lockTime.setMinutes(lockTime.getMinutes() + LOCK_TIME_MINUTES);

            await lockUser(user.id, lockTime);
        }

        return null;
    }

    /* SUCCESS RESET */
    await resetFailedAttempts(user.id);

    return user;
};