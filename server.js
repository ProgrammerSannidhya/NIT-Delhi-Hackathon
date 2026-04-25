import express from "express";

/* ================= ROUTES ================= */
import authRoutes from "./routes/authRoutes.js";
import userRoutes from "./routes/userRoutes.js";
import healthRoutes from "./routes/healthRoutes.js";
import analyzeRoutes from "./routes/analyzeRoutes.js";
import { swaggerRouter } from "./docs/swagger.js";
/* ================= MIDDLEWARE ================= */
import { errorHandling } from "./middleware/errorHandler.js";
import { globalLimiter } from "./middleware/rateLimiter.js";
import { requestLogger } from "./middleware/requestLogger.js";

/* ================= CONFIG ================= */
import { validateEnv } from "./configs/env.js";
import {
securityHeaders,
corsConfig,
sanitizeInput
} from "./configs/security.js";

/* ================= MIGRATIONS ================= */
import { runMigrations } from "./configs/migrate.js";

const app = express();

/* ================= ENV ================= */
validateEnv();

/* ================= SECURITY ================= */
app.use(securityHeaders);
app.use(corsConfig);

/* ================= GLOBAL ================= */
app.use(express.json());
app.use(sanitizeInput);
app.use(globalLimiter);
app.use(requestLogger);

/* ================= ROUTES ================= */
app.use("/auth", authRoutes);
app.use("/users", userRoutes);
app.use("/analyze", analyzeRoutes);
app.use("/", healthRoutes);
app.use(swaggerRouter);  
/* ================= ROOT ================= */
app.get("/", (req, res) => {
res.json({ message: "Server running" });
});

/* ================= ERROR ================= */
app.use(errorHandling);

/* ================= START ================= */
const start = async () => {
try {
    await runMigrations();

    app.listen(3000, () => {
    console.log("Server running on port 3000");
    });

} catch (err) {
    console.error("Startup failed:", err.message);
    console.error(err.stack);
    process.exit(1);
}
};

start();