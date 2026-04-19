// middleware/errorHandler.js

import logger from "../utils/logger.js";

export const errorHandling = (err, req, res, next) => {
    logger.error(err);

    const statusCode = err.statusCode || 500;

    res.status(statusCode).json({
        status: "error",
        message: err.message || "Something went wrong"
    });
};