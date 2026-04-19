// configs/migrate.js

import fs from "fs";
import path from "path";
import { pool } from "./db.js";

const MIGRATIONS_DIR = path.join(process.cwd(), "migrations");

export const runMigrations = async () => {
    await pool.query(`
        CREATE TABLE IF NOT EXISTS migrations (
            id SERIAL PRIMARY KEY,
            filename TEXT UNIQUE NOT NULL,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    `);

    const files = fs.readdirSync(MIGRATIONS_DIR).sort();

    for (const file of files) {
        const exists = await pool.query(
            "SELECT 1 FROM migrations WHERE filename = $1",
            [file]
        );

        if (exists.rows.length > 0) continue;

        const sql = fs.readFileSync(
            path.join(MIGRATIONS_DIR, file),
            "utf-8"
        );

        console.log(`Running migration: ${file}`);

        await pool.query("BEGIN");
        await pool.query(sql);
        await pool.query(
            "INSERT INTO migrations (filename) VALUES ($1)",
            [file]
        );
        await pool.query("COMMIT");
    }

    console.log("Migrations complete");
};