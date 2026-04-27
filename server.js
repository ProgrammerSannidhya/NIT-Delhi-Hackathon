import express from "express";

/* ================= CONFIG ================= */
import { validateEnv } from "./configs/env.js";

/* ================= ENV ================= */
validateEnv();

/* ================= WORKER ================= */
import "./workers/analyzeWorker.js";

/* ================= QUEUE ================= */
import { analysisQueue } from "./configs/queue.js";

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

/* ================= SECURITY ================= */
import {
securityHeaders,
corsConfig,
sanitizeInput
} from "./configs/security.js";

/* ================= MIGRATIONS ================= */
import { runMigrations } from "./configs/migrate.js";

const app = express();

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
res.send("Server Running");
});

/* ================= ERROR ================= */
app.use(errorHandling);

/* ================= RETRY FAILED JOBS (TEMPORARY) ================= */
const retryFailedJobs = async () => {
console.log("Retrying failed jobs...");

 
const failedJobs = await analysisQueue.getFailed();

for (const job of failedJobs) {
    try {
        console.log("Retrying job:", job.id);
        await job.retry();
    } catch (err) {
        console.error("Retry failed for job:", job.id, err.message);
    }
}

console.log("Retry process complete");
 

};

/* ================= START ================= */
const start = async () => {
try {
console.log("Running migrations...");
await runMigrations();

 
    // TEMPORARY: retry old failed jobs
    await retryFailedJobs();

    console.log("Starting server...");

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
