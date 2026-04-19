// utils/AppError.js

export class AppError extends Error {
    constructor(message, statusCode = 500) {
        super(message);
        this.statusCode = statusCode;
        this.status = String(statusCode).startsWith("4") ? "fail" : "error";

        Error.captureStackTrace(this, this.constructor);
    }
}