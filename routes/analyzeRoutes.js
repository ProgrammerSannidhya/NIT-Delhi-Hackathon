import express from "express";

import {
    analyzeRepo,
    getAnalysis,
    getUserAnalyses,
    applyChanges
} from "../controllers/analyzeController.js";

import { protect } from "../middleware/authMiddleware.js";

const router = express.Router();

router.post("/:id/apply", protect, applyChanges);

router.post("/", protect, analyzeRepo);
router.get("/", protect, getUserAnalyses);
router.get("/:id", protect, getAnalysis);

export default router;