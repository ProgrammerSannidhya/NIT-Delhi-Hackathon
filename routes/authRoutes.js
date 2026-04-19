import express from "express";

import {
    register,
    login,
    refresh,
    logout
} from "../controllers/authController.js";

import { validateAuth } from "../middleware/validate.js";
import { authLimiter } from "../middleware/rateLimiter.js";

const router = express.Router();

router.post("/register", authLimiter, validateAuth, register);
router.post("/login", authLimiter, validateAuth, login);
router.post("/refresh", refresh);
router.post("/logout", logout);

export default router;