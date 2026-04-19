export const allowSelfOrAdmin = (paramKey = "id") => {
    return (req, res, next) => {
        const user = req.user;

        if (!user) {
            return res.status(401).json({ error: "Unauthorized" });
        }

        // admin can access anything
        if (user.role === "admin") {
            return next();
        }

        const resourceId = req.params[paramKey];

        // ensure user is accessing their own record
        if (String(user.id) !== String(resourceId)) {
            return res.status(403).json({
                error: "Forbidden: you can only access your own data"
            });
        }

        next();
    };
};