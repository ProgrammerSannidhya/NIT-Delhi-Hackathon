// configs/security.js

import helmet from "helmet";
import cors from "cors";

/* ================= HELMET ================= */
export const securityHeaders = helmet({
    contentSecurityPolicy: false, // disable if not configuring CSP yet
});

/* ================= CORS ================= */
export const corsConfig = cors({
    origin: "*", // change this in production
    methods: ["GET", "POST", "PUT", "DELETE"],
    credentials: true,
});

/* ================= BASIC SANITIZATION ================= */
export const sanitizeInput = (req, res, next) => {
    if (req.body && typeof req.body === "object") {
        for (const key in req.body) {
            if (typeof req.body[key] === "string") {
                req.body[key] = req.body[key].trim();
            }
        }
    }
    next();
};