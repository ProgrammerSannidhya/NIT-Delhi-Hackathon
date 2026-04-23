import express from "express";
import cloneRepo from "../utils/clonerepo.js";
import deleteRepo from "../utils/deleterepo.js";
import { runScanner } from "../utils/runscan.js";
import { protect } from "../middleware/authMiddleware.js";
import { allowRoles } from "../middleware/roleMiddleware.js";

const router = express.Router();

const VALID_TYPES = ["application", "library", "framework", "cli", "plugin"];

/**
 * @swagger
 * /analyze:
 *   post:
 *     summary: Analyze a GitHub repository for dead code
 *     security:
 *       - bearerAuth: []
 *     tags:
 *       - Analyze
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - repoLink
 *             properties:
 *               repoLink:
 *                 type: string
 *                 example: "https://github.com/user/repo"
 *               userType:
 *                 type: string
 *                 enum: [application, library, framework, cli, plugin]
 *                 description: >
 *                   Optional. When provided, forces this repo type instead of
 *                   the auto-detected one (override = true).
 *     responses:
 *       200:
 *         description: Analysis result
 *       400:
 *         description: Invalid input
 *       401:
 *         description: Unauthorized
 *       500:
 *         description: Analysis failed
 */
router.post("/", protect, allowRoles("admin", "user"), async (req, res, next) => {
    let repoPath;
    if (!req.body || typeof req.body !== "object") {
    return res.status(400).json({
        error: "Request body is missing or not JSON. Set Content-Type: application/json."
    });
}

    try {
        const { repoLink, userType } = req.body;

        // --- input validation -------------------------------------------

        if (!repoLink || typeof repoLink !== "string") {
            return res.status(400).json({ error: "Invalid repoLink" });
        }

        if (!repoLink.startsWith("https://github.com/")) {
            return res.status(400).json({
                error: "Only GitHub repos are allowed"
            });
        }

        // userType is optional; if provided it must be one of the known values
        if (userType !== undefined && userType !== null) {
            if (typeof userType !== "string" || !VALID_TYPES.includes(userType)) {
                return res.status(400).json({
                    error: `Invalid userType. Must be one of: ${VALID_TYPES.join(", ")}`
                });
            }
        }

        // --- pipeline ---------------------------------------------------

        repoPath = await cloneRepo(repoLink);

        // Pass override=true only when the caller explicitly supplied a type.
        // This matches the new runScanner(repoPath, userType, override) signature:
        //   override=false → autoType always wins (userType ignored)
        //   override=true  → userType forces the analysis mode
        const override = Boolean(userType);
        const result   = await runScanner(repoPath, userType ?? null, override);

        if (result?.error) {
            return res.status(500).json({ error: result.error });
        }

        return res.status(200).json(result);

    } catch (err) {
        next(err);
    } finally {
        if (repoPath) {
            try {
                deleteRepo(repoPath);
            } catch (e) {
                console.error("cleanup failed:", e.message);
            }
        }
    }
});

export default router;