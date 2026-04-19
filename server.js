import express from "express";

/* ================= UTILS ================= */
import cloneRepo from "./utils/clonerepo.js";
import deleteRepo from "./utils/deleterepo.js";
import { runScanner } from "./utils/runscan..js";

/* ================= ROUTES ================= */
import authRoutes from "./routes/authRoutes.js";
import userRoutes from "./routes/userRoutes.js";
import healthRoutes from "./routes/healthRoutes.js";

/* ================= MIDDLEWARE ================= */
import { protect } from "./middleware/authMiddleware.js";
import { allowRoles } from "./middleware/roleMiddleware.js";
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
app.use("/", healthRoutes);

/* ================= ROOT ================= */
app.get("/", (req, res) => {
    res.json({ message: "Server running" });
});

/* ================= ANALYZE ================= */
app.post(
    "/analyze",
    protect,
    allowRoles("admin", "user"),
    async (req, res, next) => {
        let repoPath;

        try {
            const { repoLink, userType } = req.body;

            if (!repoLink || typeof repoLink !== "string") {
                return res.status(400).json({ error: "Invalid repoLink" });
            }

            if (!repoLink.startsWith("https://github.com/")) {
                return res.status(400).json({
                    error: "Only GitHub repos allowed"
                });
            }

            /* ================= CLONE ================= */
            repoPath = await cloneRepo(repoLink);

            console.log("CLONED PATH:", repoPath);

            /* ================= SCAN ================= */
            const result = await runScanner(repoPath, userType);

            if (result?.error) {
                return res.status(500).json({ error: result.error });
            }

            return res.status(200).json(result);

        } catch (err) {
            next(err);
        } finally {
            /* ================= CLEANUP ================= */
            if (repoPath) {
                try {
                    console.log("DELETING PATH:", repoPath);
                    deleteRepo(repoPath);
                } catch (e) {
                    console.error("cleanup failed:", e.message);
                }
            }
        }
    }
);

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
        process.exit(1);
    }
};

start();