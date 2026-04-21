import express from "express";
import cloneRepo from "../utils/clonerepo.js";
import deleteRepo from "../utils/deleterepo.js";
import { runScanner } from "../utils/runscan.js";
import { protect } from "../middleware/authMiddleware.js";
import { allowRoles } from "../middleware/roleMiddleware.js";

const router = express.Router();

/**
 * @swagger
 * /analyze:
 *   post:
 *     summary: Analyze a GitHub repository
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
 *             properties:
 *               repoLink:
 *                 type: string
 *               userType:
 *                 type: string
 *     responses:
 *       200:
 *         description: Analysis result
 *       400:
 *         description: Invalid input
 *       401:
 *         description: Unauthorized
 */
router.post("/", protect, allowRoles("admin", "user"), async (req, res, next) => {
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

        repoPath = await cloneRepo(repoLink);

        const result = await runScanner(repoPath, userType);

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