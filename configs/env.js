// configs/env.js

import dotenv from "dotenv";

dotenv.config();

const requiredEnv = [
    "DATABASE_URL",
    "JWT_SECRET",
    "JWT_EXPIRES_IN"
];

export const validateEnv = () => {
    const missing = [];

    for (const key of requiredEnv) {
        if (!process.env[key]) {
            missing.push(key);
        }
    }

    if (missing.length > 0) {
        console.error("Missing ENV variables:", missing.join(", "));
        process.exit(1);
    }

    console.log("ENV validated");
};