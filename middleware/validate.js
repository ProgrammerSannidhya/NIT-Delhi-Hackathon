export const validateAuth = (req, res, next) => {
    const { username, password } = req.body;

    if (!username || typeof username !== "string") {
        return res.status(400).json({ error: "Invalid username" });
    }

    if (!password || password.length < 4) {
        return res.status(400).json({ error: "Password too short" });
    }

    next();
};