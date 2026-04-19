// middleware/userValidation.js

export const validateUserCreate = (req, res, next) => {
    const { username } = req.body;

    if (!username || typeof username !== "string") {
        return res.status(400).json({
            error: "Username is required and must be a string"
        });
    }

    if (username.length < 3 || username.length > 30) {
        return res.status(400).json({
            error: "Username must be between 3 and 30 characters"
        });
    }

    next();
};

export const validateUserUpdate = (req, res, next) => {
    const { username } = req.body;

    if (!username || typeof username !== "string") {
        return res.status(400).json({
            error: "Username is required and must be a string"
        });
    }

    if (username.length < 3 || username.length > 30) {
        return res.status(400).json({
            error: "Username must be between 3 and 30 characters"
        });
    }

    next();
};

export const validateUserId = (req, res, next) => {
    const { id } = req.params;

    if (!id || isNaN(Number(id))) {
        return res.status(400).json({
            error: "Invalid user ID"
        });
    }

    next();
};