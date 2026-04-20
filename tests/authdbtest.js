// tests/authdbtest.js

import fetch from "node-fetch";

const BASE_URL = "http://localhost:3000";

/* ================= HEALTH CHECK ================= */
const testHealth = async () => {
    try {
        const res = await fetch(`${BASE_URL}/`);
        const data = await res.json();

        console.log("Health Test:", data);
    } catch (err) {
        console.error("Health Test Failed:", err.message);
    }
};

/* ================= AUTH REGISTER ================= */
const testRegister = async () => {
    try {
        const username =
            "user_" + Math.random().toString(36).substring(2, 8);

        const password = "StrongPass123!";

        const res = await fetch(`${BASE_URL}/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        const data = await res.json();

        console.log("Register Test:", data);

        if (!res.ok || data.error) {
            console.log("Register failed");
            return null;
        }

        return { username, password };

    } catch (err) {
        console.error("Register Failed:", err.message);
        return null;
    }
};

/* ================= AUTH LOGIN ================= */
const testLogin = async (username, password) => {
    try {
        const res = await fetch(`${BASE_URL}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        const data = await res.json();

        console.log("Login Test:", data);

        if (!res.ok || data.error) {
            console.log("Login failed");
            return null;
        }

        // ✅ FIX: use accessToken from your backend
        return data.data?.accessToken;

    } catch (err) {
        console.error("Login Failed:", err.message);
        return null;
    }
};

/* ================= PROTECTED ROUTE ================= */
const testProtected = async (token) => {
    try {
        const res = await fetch(`${BASE_URL}/auth/me`, {
            headers: {
                Authorization: `Bearer ${token}`
            }
        });

        const data = await res.json();

        console.log("Protected Route Test:", data);

    } catch (err) {
        console.error("Protected Failed:", err.message);
    }
};

/* ================= RUN ALL ================= */
const runTests = async () => {
    await testHealth();

    const creds = await testRegister();
    if (!creds) return;

    const token = await testLogin(creds.username, creds.password);
    if (!token) return;

    await testProtected(token);
};

runTests();