// middleware/requestLogger.js

import logger from "../utils/logger.js";

export const requestLogger = (req, res, next) => {
    const start = Date.now();

    res.on("finish", () => {
        const duration = Date.now() - start;

        logger.info({
            method: req.method,
            url: req.originalUrl,
            status: res.statusCode,
            userId: req.user?.id || null,
            duration: `${duration}ms`,
            ip: req.ip
        });
    });

    next();
};