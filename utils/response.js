// utils/response.js

export const success = (res, data = null, message = "OK", status = 200) => {
    return res.status(status).json({
        status: "success",
        message,
        data
    });
};

export const fail = (res, message = "Bad Request", status = 400) => {
    return res.status(status).json({
        status: "fail",
        message
    });
};

export const error = (res, message = "Something went wrong", status = 500) => {
    return res.status(status).json({
        status: "error",
        message
    });
};