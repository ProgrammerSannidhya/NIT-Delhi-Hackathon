// routes/healthRoutes.js

import express from "express";
import {
    healthCheck,
    readinessCheck
} from "../controllers/healthController.js";

const router = express.Router();

router.get("/health", healthCheck);
router.get("/ready", readinessCheck);

export default router;