import express from "express";

import {
    createUser,
    getAllUsers,
    getUserById,
    updateUser,
    deleteUser
} from "../controllers/userController.js";

import { protect } from "../middleware/authMiddleware.js";
import { allowRoles } from "../middleware/roleMiddleware.js";
import { allowSelfOrAdmin } from "../middleware/ownershipMiddleware.js";
import {
    validateUserCreate,
    validateUserUpdate,
    validateUserId
} from "../middleware/userValidation.js";

const router = express.Router();



/* ================= ADMIN ONLY ================= */
router.post(
    "/",
    protect,
    allowRoles("admin"),
    validateUserCreate,
    createUser
);

router.get(
    "/",
    protect,
    allowRoles("admin"),
    getAllUsers
);

router.delete(
    "/:id",
    protect,
    allowRoles("admin"),
    validateUserId,
    deleteUser
);

/* ================= ADMIN + OWNER ================= */
router.get(
    "/:id",
    protect,
    allowRoles("admin", "user"),
    validateUserId,
    allowSelfOrAdmin("id"),
    getUserById
);

router.put(
    "/:id",
    protect,
    allowRoles("admin", "user"),
    validateUserId,
    validateUserUpdate,
    allowSelfOrAdmin("id"),
    updateUser
);

export default router;