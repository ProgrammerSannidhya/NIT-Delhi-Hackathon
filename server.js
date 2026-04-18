import express from "express";
import cloneRepo from "./utils/clonerepo.js";
import deleteRepo from "./utils/deleterepo.js";
import { runScanner } from "./utils/runscan..js";

const app = express();
app.use(express.json());

app.get("/", (req, res) => {
res.json({ message: "Server is running" });
});

app.post("/analyze", async (req, res) => {
let repoPath;

try {
    const { repoLink, userType } = req.body;

    // ---------- validation ----------
    if (!repoLink || typeof repoLink !== "string") {
    return res.status(400).json({ error: "Invalid repoLink" });
    }

    if (!repoLink.startsWith("https://github.com/")) {
    return res.status(400).json({ error: "Only GitHub repos allowed" });
    }

    // ---------- clone ----------
    repoPath = await cloneRepo(repoLink);

    // ---------- run scanner ----------
    const result = await runScanner(repoPath, userType);

    if (result.error) {
    return res.status(500).json({
        error: result.error
    });
    }

    // ---------- normalize response ----------
    const files = (result.unusedFiles || []).map((f) => ({
    path: f.file || f.path,
    unused: true,
    exports: f.exports || [],
    confidence: f.confidence || 0
    }));

    const deps = (result.unusedDeps || []).map((d) => ({
    name: d.name || d,
    unused: true,
    confidence: d.confidence || 0
    }));

    const response = {
    repo: {
        autoType: result.repoType?.autoType || "unknown",
        userType: result.repoType?.userType || null,
        finalType: result.repoType?.finalType || "unknown",
        confidence: result.repoType?.confidence || 0,
        overridden: result.repoType?.overridden || false
    },

    files,
    deps,

    meta: {
        totalFiles: result.summary?.files || 0,
        totalExports: result.summary?.exports || 0,
        totalDeps: result.summary?.deps || 0
    },

    scores: result.scores || {
        overall: 100,
        reliability: 0
    }
    };

    return res.status(200).json(response);

} catch (err) {
    return res.status(500).json({
    error: err.message || "analysis failed"
    });

} finally {
    if (repoPath) {
    try {
        await deleteRepo(repoPath);
    } catch (e) {
        console.error("cleanup failed:", e.message);
    }
    }
}
});

app.listen(3000, () => {
console.log("Server running on port 3000");
});