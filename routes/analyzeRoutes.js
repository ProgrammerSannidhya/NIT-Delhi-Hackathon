import express from "express";
import {
startAnalysis,
fetchAnalysisById,
fetchUserAnalyses,
enqueueApplyJob
} from "../services/analyzeServices.js";

import { protect } from "../middleware/authMiddleware.js";

const router = express.Router();

/* ================= START ================= */
router.post("/", protect, async (req, res) => {
try {
const { repoLink, userType } = req.body;
const userId = req.user.id;

    
    const result = await startAnalysis(userId, repoLink, userType);

    res.status(202).json(result);

} catch (err) {
    res.status(500).json({
        status: "failed",
        message: err.message
    });
}
    

});

/* ================= STATUS ================= */
router.get("/:id", protect, async (req, res) => {
try {
const userId = req.user.id;
const id = req.params.id;

    
    const data = await fetchAnalysisById(id, userId);

    if (!data) {
        return res.status(404).json({
            status: "failed",
            message: "Not found"
        });
    }

    res.json(data);

} catch (err) {
    res.status(500).json({
        status: "failed",
        message: err.message
    });
}
    

});

/* ================= APPLY ================= */
router.post("/:id/apply", protect, async (req, res) => {
try {
const userId = req.user.id;
const analysisId = req.params.id;

    
    const { files, deps } = req.body;

    const result = await enqueueApplyJob({
        analysisId,
        userId,
        files,
        deps
    });

    res.json(result);

} catch (err) {
    res.status(400).json({
        status: "failed",
        message: err.message
    });
}
    

});

/* ================= USER ================= */
router.get("/", protect, async (req, res) => {
const data = await fetchUserAnalyses(req.user.id);
res.json(data);
});

export default router;
