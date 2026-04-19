// controllers/healthController.js

import { pool } from "../configs/db.js";

export const healthCheck = async (req, res) => {
    res.status(200).json({
        status: "ok",
        uptime: process.uptime(),
        timestamp: new Date().toISOString()
    });
};

export const readinessCheck = async (req, res) => {
    try {
        // check DB connectivity
        await pool.query("SELECT 1");

        res.status(200).json({
            status: "ready",
            db: "connected",
            timestamp: new Date().toISOString()
        });

    } catch (err) {
        res.status(503).json({
            status: "not_ready",
            db: "disconnected",
            error: err.message
        });
    }
};