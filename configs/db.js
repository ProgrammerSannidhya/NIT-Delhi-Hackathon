// configs/db.js

import pkg from "pg";
import dotenv from "dotenv";

dotenv.config();

const { Pool } = pkg;

export const pool = new Pool({
    user: process.env.DB_USER,
    host: process.env.DB_HOST,
    database: process.env.DATABASE,
    port: process.env.DB_PORT,
    password: process.env.DB_PASSWORD,
});

pool.on("connect", () => {
    console.log("Database connected");
});